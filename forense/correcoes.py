"""Correções do analista: registradas, conferidas pela máquina e aplicadas como sobreposição.

- O log (analise/correcoes.jsonl) só cresce: nada se apaga, e a correção de uma correção é uma linha
  nova. Serve para a depuração: cada linha traz o valor original, o proposto, o motivo, o trecho da
  fonte, o documento e a página, e a versão do app, do modelo e das instruções que geraram o dado.
- A correção NÃO é aceita às cegas: a máquina confere se o valor proposto aparece no texto da
  página de onde o dado saiu e marca «confere com o texto», «não encontrado no texto» ou «não
  verificável» (categoria, resumo). A depuração parte dessa marca para ver se o erro existia.
- Na tela e no relatório, o valor corrigido aparece marcado (✎); o original continua guardado.
"""

import hashlib
import json
import re

from . import EXTRATOR_VERSAO, __version__
from .caso import Caso, _usuario, agora, ler_json
from .citacao import aparece
from .regex_br import extrair_datas

CAMPOS = {
    "pessoas": ["nome", "cargo", "empresa"],
    "empresas": ["nome", "cnpj"],
    "eventos": ["data", "participantes", "categoria", "descricao_ia"],
    "mensagem": ["de", "para", "data", "assunto"],
}
NAO_VERIFICAVEIS = {"categoria", "descricao_ia", "assunto"}


def caminho(caso: Caso):
    return caso.analise / "correcoes.jsonl"


def _texto_da_pagina(caso: Caso, documento_id: str, pagina: int | None) -> str:
    arq = caso.extraido / f"{documento_id}.json"
    if not arq.exists():
        return ""
    doc = ler_json(arq)
    paginas = doc["paginas"] if pagina is None else [p for p in doc["paginas"] if p["n"] == pagina]
    return "\n".join(p.get("texto") or "" for p in paginas)


def conferir(campo: str, valor: str, texto: str) -> str:
    """Marca da máquina para o valor proposto, à vista do texto da fonte."""
    valor = (valor or "").strip()
    if campo in NAO_VERIFICAVEIS:
        return "não verificável"
    if not valor:
        return "valor removido"
    if campo == "data":
        return "confere com o texto" if valor[:10] in {d["data"] for d in extrair_datas(texto)} else "não encontrado no texto"
    if campo == "cnpj":
        digitos = re.sub(r"\D", "", valor)
        return "confere com o texto" if digitos and digitos in re.sub(r"\D", "", texto) else "não encontrado no texto"
    if campo in ("de", "para"):  # «Nome <endereço>; Nome»: basta o nome ou o endereço de cada um aparecer
        from .comunicacoes import participantes
        ok = all((n and aparece(n, texto)) or (e and e in texto.lower()) for n, e in participantes(valor))
        return "confere com o texto" if ok else "não encontrado no texto"
    partes = [p.strip() for p in re.split(r"[;,]", valor) if p.strip()] if campo == "participantes" else [valor]
    return "confere com o texto" if all(aparece(p, texto) for p in partes) else "não encontrado no texto"


def registrar(caso: Caso, alvo: dict, campo: str, valor_anterior, valor_proposto: str, motivo: str,
              contexto: dict | None = None) -> dict:
    """alvo: {"tipo": "achado"|"mensagem", "id", "documento_id", "pagina", "localizador", "trecho"}."""
    texto = _texto_da_pagina(caso, alvo["documento_id"], alvo.get("pagina"))
    linha = {
        "id": hashlib.sha1(f"{agora()}|{alvo['id']}|{campo}|{valor_proposto}".encode()).hexdigest()[:12],
        "quando": agora(), "usuario": _usuario(),
        "alvo": alvo, "campo": campo,
        "valor_anterior": valor_anterior, "valor_proposto": (valor_proposto or "").strip(),
        "motivo": (motivo or "").strip(),
        "conferencia_maquina": conferir(campo, valor_proposto, texto),
        "versoes": {"app": __version__, "extrator": EXTRATOR_VERSAO, **(contexto or {})},
    }
    caso.analise.mkdir(parents=True, exist_ok=True)
    with open(caminho(caso), "a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    caso.registrar("correcao_registrada", correcao=linha["id"], alvo=alvo["id"], campo=campo,
                   conferencia=linha["conferencia_maquina"])
    return linha


def ler(caso: Caso) -> list[dict]:
    if not caminho(caso).exists():
        return []
    with open(caminho(caso), encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def vigentes(caso: Caso) -> dict[tuple, dict]:
    """(id do alvo, campo) -> a correção mais recente."""
    saida = {}
    for c in ler(caso):
        saida[(c["alvo"]["id"], c["campo"])] = c
    return saida


def aplicar_em_achados(achados: list[dict], correcoes: dict[tuple, dict]) -> list[dict]:
    """Sobrepõe as correções aos dados dos achados, guardando o original e a marca da conferência."""
    saida = []
    for a in achados:
        mudancas = {campo: c for (alvo, campo), c in correcoes.items() if alvo == a["id"]}
        if mudancas:
            a = {**a, "dados": dict(a["dados"]), "dados_originais": a["dados"], "correcoes": {}}
            for campo, c in mudancas.items():
                valor = c["valor_proposto"]
                if campo == "participantes":
                    valor = [p.strip() for p in re.split(r"[;,]", valor) if p.strip()]
                if valor in ("", []):
                    a["dados"].pop(campo, None)
                else:
                    a["dados"][campo] = valor
                a["correcoes"][campo] = {"conferencia": c["conferencia_maquina"], "quando": c["quando"],
                                         "motivo": c["motivo"], "anterior": c["valor_anterior"]}
        saida.append(a)
    return saida
