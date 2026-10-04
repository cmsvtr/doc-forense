"""Etapa 2: extração com a IA local, com verificação pela máquina (camada analítica).

O modelo PROPÕE pessoas, empresas e eventos de cada trecho; a máquina CONFERE. Regras:
- todo item traz um trecho literal; trecho que não está no documento descarta o item;
- a página é a da máquina (onde o trecho foi achado), nunca a que o modelo disser;
- nome, empresa, CNPJ, data e participante têm de aparecer no texto; o que não aparece sai;
- a «descrição» de um evento é resumo do modelo: aparece como tal e nunca como citação.
Nada aqui é conclusão. Todo item nasce «pendente» e só o analista o valida (revisao.json).
"""

import hashlib
import json
import re
import time
from pathlib import Path

from . import ia
from .caso import Caso, agora, escrever_json_atomico, ler_json
from .citacao import aparece, localizar
from .regex_br import cnpj_valido, extrair_datas
from .sei import localizador

PALAVRAS_POR_TRECHO = 1200   # calibrar pela velocidade medida no computador do usuário
CATEGORIAS_EVENTO = [
    "fixação de preços ou condições",
    "divisão de mercado, clientes ou lotes",
    "proposta de cobertura, supressão ou rodízio em licitação",
    "troca de informação sensível",
    "reunião ou contato entre concorrentes",
    "outro",
]

ESQUEMA = {
    "type": "object",
    "properties": {
        "pessoas": {"type": "array", "items": {"type": "object", "properties": {
            "nome": {"type": "string"}, "cargo": {"type": "string"}, "empresa": {"type": "string"},
            "trecho": {"type": "string"}}, "required": ["nome", "trecho"]}},
        "empresas": {"type": "array", "items": {"type": "object", "properties": {
            "nome": {"type": "string"}, "cnpj": {"type": "string"},
            "trecho": {"type": "string"}}, "required": ["nome", "trecho"]}},
        "eventos": {"type": "array", "items": {"type": "object", "properties": {
            "data": {"type": "string"}, "descricao": {"type": "string"},
            "participantes": {"type": "array", "items": {"type": "string"}},
            "categoria": {"type": "string", "enum": CATEGORIAS_EVENTO},
            "trecho": {"type": "string"}}, "required": ["descricao", "categoria", "trecho"]}},
    },
    "required": ["pessoas", "empresas", "eventos"],
}

INSTRUCOES = """Você extrai informações de documentos de uma investigação de cartel.
Regras:
1. Use só o que está escrito no trecho. Não deduza, não complete, não opine.
2. Em cada item, copie em "trecho" as palavras exatas do documento (de 5 a 40 palavras), sem corrigir nada.
3. Pessoas e empresas: só as nomeadas no texto. Cargo e empresa da pessoa só se o texto disser.
4. Eventos: o que alguém fez, combinou ou discutiu. "descricao" em uma frase curta.
5. Datas no formato AAAA-MM-DD, só quando o texto der dia, mês e ano; senão, deixe vazio.
6. Se não houver nada de um tipo, devolva a lista vazia."""

VERSAO_EXTRACAO = "1"
_HASH_PROMPT = hashlib.sha256((INSTRUCOES + json.dumps(ESQUEMA, sort_keys=True) + VERSAO_EXTRACAO).encode()).hexdigest()[:12]


# ------------------------------------------------------------------ trechos

def dividir_em_trechos(doc: dict, palavras_max: int = PALAVRAS_POR_TRECHO) -> list[dict]:
    """Agrupa páginas em trechos de até palavras_max palavras. Página maior que o limite é partida
    por parágrafos (as partes continuam com o número da página)."""
    partes: list[dict] = []
    for pg in doc["paginas"]:
        texto = (pg.get("texto") or "").strip()
        if not texto:
            continue
        if len(texto.split()) <= palavras_max:
            partes.append({"n": pg["n"], "texto": texto})
            continue
        bloco: list[str] = []
        for par in re.split(r"\n\s*\n", texto):
            if bloco and len(" ".join(bloco + [par]).split()) > palavras_max:
                partes.append({"n": pg["n"], "texto": "\n\n".join(bloco)})
                bloco = []
            bloco.append(par)
        if bloco:
            partes.append({"n": pg["n"], "texto": "\n\n".join(bloco)})

    trechos, atual, contagem = [], [], 0
    for parte in partes:
        n_pal = len(parte["texto"].split())
        if atual and contagem + n_pal > palavras_max:
            trechos.append(atual)
            atual, contagem = [], 0
        atual.append(parte)
        contagem += n_pal
    if atual:
        trechos.append(atual)

    saida = []
    for k, paginas in enumerate(trechos, 1):
        marcado = "\n\n".join(f"[p. {p['n']}]\n{p['texto']}" for p in paginas)
        saida.append({
            "id": f"{doc['documento_id']}-t{k:03d}",
            "paginas": paginas,
            "texto_marcado": marcado,
            "hash": hashlib.sha256(marcado.encode("utf-8")).hexdigest()[:16],
        })
    return saida


# ------------------------------------------------------------------ verificação

def _id_achado(doc_id: str, tipo: str, pagina: int, chave: str, trecho: str) -> str:
    base = f"{doc_id}|{tipo}|{pagina}|{chave.lower().strip()}|{' '.join(trecho.lower().split())}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def verificar(resposta: dict, trecho: dict, doc: dict) -> tuple[list[dict], list[dict]]:
    """(achados verificados, descartados com o motivo)."""
    texto_trecho = "\n".join(p["texto"] for p in trecho["paginas"])
    datas_no_texto = {d["data"] for d in extrair_datas(texto_trecho)}
    achados, descartados = [], []

    def recusar(tipo, item, motivo):
        descartados.append({"tipo": tipo, "item": item, "motivo": motivo})

    for tipo in ("pessoas", "empresas", "eventos"):
        for item in resposta.get(tipo) or []:
            if not isinstance(item, dict):
                continue
            achado_fonte = localizar(item.get("trecho", ""), trecho["paginas"])
            if not achado_fonte:
                recusar(tipo, item, "trecho não encontrado no documento")
                continue
            dados, alertas = {}, []
            if tipo in ("pessoas", "empresas"):
                nome = (item.get("nome") or "").strip()
                if not nome or not aparece(nome, texto_trecho):
                    recusar(tipo, item, "nome não aparece no texto")
                    continue
                dados["nome"] = nome
                for campo in ("cargo", "empresa"):
                    valor = (item.get(campo) or "").strip()
                    if valor:
                        if aparece(valor, texto_trecho):
                            dados[campo] = valor
                        else:
                            alertas.append(f"{campo} «{valor}» proposto pela IA não aparece no texto; descartado")
                cnpj = (item.get("cnpj") or "").strip()
                if cnpj:
                    digitos = re.sub(r"[./\-\s]", "", cnpj.upper())
                    if cnpj_valido(digitos) and digitos in re.sub(r"[./\-\s]", "", texto_trecho.upper()):
                        dados["cnpj"] = cnpj
                    else:
                        alertas.append(f"CNPJ «{cnpj}» inválido ou ausente do texto; descartado")
                chave = nome
            else:
                categoria = item.get("categoria") if item.get("categoria") in CATEGORIAS_EVENTO else "outro"
                dados.update(descricao_ia=(item.get("descricao") or "").strip(), categoria=categoria)
                data = (item.get("data") or "").strip()
                if data:
                    if data in datas_no_texto:
                        dados["data"] = data
                    else:
                        alertas.append(f"data «{data}» proposta pela IA não está no texto; descartada")
                participantes = [p for p in (item.get("participantes") or []) if isinstance(p, str) and p.strip()]
                dados["participantes"] = [p for p in participantes if aparece(p, texto_trecho)]
                if len(dados["participantes"]) < len(participantes):
                    fora = [p for p in participantes if p not in dados["participantes"]]
                    alertas.append(f"participante(s) fora do texto descartado(s): {', '.join(fora)}")
                chave = categoria
            if not achado_fonte["literal"]:
                alertas.append(f"trecho achado por semelhança ({achado_fonte['similaridade']:.0%}), não letra por letra")
            achados.append({
                "id": _id_achado(doc["documento_id"], tipo, achado_fonte["pagina"], chave, achado_fonte["trecho_fonte"]),
                "tipo": tipo, "dados": dados,
                "documento_id": doc["documento_id"], "localizador": localizador(doc, [achado_fonte["pagina"]]),
                "caminho": doc["arquivo"]["caminhos"][0], "pagina": achado_fonte["pagina"],
                "trecho_fonte": achado_fonte["trecho_fonte"], "literal": achado_fonte["literal"],
                "similaridade": achado_fonte["similaridade"], "alertas": alertas, "trecho_id": trecho["id"],
            })
    return achados, descartados


# ------------------------------------------------------------------ chamada ao modelo

def perguntar(trecho: dict, doc: dict, modelo: str) -> tuple[dict, dict]:
    """(resposta do modelo, medidas). Levanta exceção se o Ollama falhar."""
    r = ia._pedir("/api/chat", {
        "model": modelo, "stream": False, "format": ESQUEMA,
        "messages": [
            {"role": "system", "content": INSTRUCOES},
            {"role": "user", "content": f"Documento: {localizador(doc)}\n\nTRECHO (as marcas [p. N] indicam a página):\n"
                                        f"{trecho['texto_marcado']}\n\nExtraia pessoas, empresas e eventos."},
        ],
        "options": {"temperature": 0, "seed": 1, "num_ctx": ia.CONTEXTO, "num_predict": 1500},
        "keep_alive": "30m",
    }, tempo=1800)
    conteudo = (r.get("message") or {}).get("content") or "{}"
    try:
        resposta = json.loads(conteudo)
    except ValueError:
        resposta = {"_json_invalido": conteudo[:2000]}
    medidas = {k: r.get(k) for k in ("prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration", "total_duration")}
    return resposta, medidas


# ------------------------------------------------------------------ por documento (retomável)

def caminho_resultado(caso: Caso, doc_id: str) -> Path:
    return caso.analise / "ia" / f"{doc_id}.json"


def analisar_documento(caso: Caso, doc: dict, modelo: str, digest: str | None,
                       palavras_max: int = PALAVRAS_POR_TRECHO, ao_terminar_trecho=None) -> dict:
    """Analisa os trechos ainda não feitos (mesmo modelo, mesmo prompt, mesmo texto) e grava após
    cada trecho: interrompido, continua de onde parou."""
    destino = caminho_resultado(caso, doc["documento_id"])
    anterior = ler_json(destino) if destino.exists() else {}
    feitos = {t["id"]: t for t in anterior.get("trechos", [])
              if t.get("chave") == [modelo, digest, _HASH_PROMPT, t.get("hash")]}
    trechos = dividir_em_trechos(doc, palavras_max)
    resultado = {
        "schema": "doc-forense/analise-ia@1", "documento_id": doc["documento_id"],
        "modelo": modelo, "modelo_digest": digest, "prompt_hash": _HASH_PROMPT,
        "palavras_por_trecho": palavras_max, "atualizado_em": agora(), "trechos": [],
    }
    for k, t in enumerate(trechos, 1):
        if t["id"] in feitos and feitos[t["id"]].get("hash") == t["hash"]:
            resultado["trechos"].append(feitos[t["id"]])
            continue
        inicio = time.monotonic()
        try:
            resposta, medidas = perguntar(t, doc, modelo)
            achados, descartados = verificar(resposta, t, doc)
            registro = {"id": t["id"], "hash": t["hash"], "paginas": [p["n"] for p in t["paginas"]],
                        "chave": [modelo, digest, _HASH_PROMPT, t["hash"]], "resposta_bruta": resposta,
                        "achados": achados, "descartados": descartados, "medidas": medidas,
                        "duracao_s": round(time.monotonic() - inicio, 1)}
        except Exception as e:  # Ollama fora do ar, tempo esgotado: o trecho fica para a próxima rodada
            registro = {"id": t["id"], "hash": t["hash"], "paginas": [p["n"] for p in t["paginas"]],
                        "erro": f"{type(e).__name__}: {e}", "achados": [], "descartados": []}
        resultado["trechos"].append(registro)
        resultado["atualizado_em"] = agora()
        escrever_json_atomico(destino, resultado)
        if ao_terminar_trecho:
            ao_terminar_trecho(k, len(trechos), registro)
    escrever_json_atomico(destino, resultado)
    return resultado


# ------------------------------------------------------------------ revisão pelo analista

def caminho_revisao(caso: Caso) -> Path:
    return caso.analise / "revisao.json"


def ler_revisao(caso: Caso) -> dict:
    p = caminho_revisao(caso)
    return ler_json(p) if p.exists() else {}


def marcar(caso: Caso, achado_id: str, status: str, nota: str = "") -> None:
    """status: validado | rejeitado | pendente. A revisão fica fora do resultado da IA: refazer a
    análise não apaga o que o analista decidiu."""
    if status not in ("validado", "rejeitado", "pendente"):
        raise ValueError(status)
    from .caso import _usuario

    rev = ler_revisao(caso)
    rev[achado_id] = {"status": status, "nota": nota, "por": _usuario(), "quando": agora()}
    escrever_json_atomico(caminho_revisao(caso), rev)
    caso.registrar("achado_revisado", achado=achado_id, status=status)


def achados_do_caso(caso: Caso) -> list[dict]:
    """Todos os achados verificados, com o status da revisão (pendente se não revisado)."""
    rev = ler_revisao(caso)
    saida, vistos = [], set()
    pasta = caso.analise / "ia"
    for arq in sorted(pasta.glob("*.json")) if pasta.is_dir() else []:
        for t in ler_json(arq).get("trechos", []):
            for a in t.get("achados", []):
                if a["id"] in vistos:
                    continue
                vistos.add(a["id"])
                saida.append({**a, "revisao": rev.get(a["id"], {"status": "pendente"})})
    return saida


# ------------------------------------------------------------------ o caso inteiro

def analisar_caso(caso: Caso, modelo: str = ia.MODELO_PADRAO, documentos: list[str] | None = None,
                  primeiros: int | None = None, palavras_max: int = PALAVRAS_POR_TRECHO, log=print) -> dict:
    """Roda a IA nos documentos na ordem da triagem (os mais relevantes primeiro).
    documentos: ids escolhidos pelo analista; primeiros: só os N primeiros da triagem."""
    from .processamento import Progresso, em_execucao
    from .triagem import ler_triagem

    if em_execucao(caso):
        raise RuntimeError("Já existe um processamento em andamento para este caso.")
    s = ia.situacao(modelo)
    if not s["ativo"] or not s["modelo_baixado"]:
        raise RuntimeError(s["erro"] or f"Modelo {modelo} não baixado (ollama pull {modelo}).")
    if any("cloud" in m.lower() for m in [modelo]):
        raise RuntimeError("Modelo que roda na nuvem: os documentos sairiam do computador. Use um modelo local.")

    por_id = {d["documento_id"]: d for d in caso.documentos()}
    ordem = [r["documento_id"] for r in (ler_triagem(caso) or {}).get("documentos", [])]
    ordem += [i for i in por_id if i not in ordem]
    if documentos:
        ordem = [i for i in ordem if i in set(documentos)]
    if primeiros:
        ordem = ordem[:primeiros]
    alvo = [por_id[i] for i in ordem if i in por_id]

    resumo = {"documentos": 0, "trechos": 0, "achados": 0, "descartados": 0, "erros": 0}
    with Progresso(caso) as prog:
        caso.registrar("ia_iniciada", modelo=modelo, digest=s["digest"], documentos=len(alvo),
                       prompt_hash=_HASH_PROMPT, palavras_por_trecho=palavras_max)
        prog.atualizar(etapa="análise com IA", total=len(alvo), concluidos=0)
        for k, doc in enumerate(alvo, 1):
            nome = doc["arquivo"]["nome"]

            def progresso_trecho(i, n, reg, nome=nome):
                prog.atualizar(atual=f"{nome}: trecho {i}/{n}")
                log(f"    {nome} trecho {i}/{n}: {len(reg.get('achados', []))} achado(s), "
                    f"{len(reg.get('descartados', []))} descartado(s){' — ERRO ' + reg['erro'] if reg.get('erro') else ''}")

            r = analisar_documento(caso, doc, modelo, s["digest"], palavras_max, progresso_trecho)
            resumo["documentos"] += 1
            for t in r["trechos"]:
                resumo["trechos"] += 1
                resumo["achados"] += len(t.get("achados", []))
                resumo["descartados"] += len(t.get("descartados", []))
                resumo["erros"] += 1 if t.get("erro") else 0
            log(f"  [{k}/{len(alvo)}] {nome}: {len(r['trechos'])} trecho(s)")
            prog.atualizar(concluidos=k)
        caso.registrar("ia_concluida", **resumo)
        prog.atualizar(etapa="concluído", resumo=resumo)
    log(f"[✓] IA concluída: {resumo}")
    return resumo
