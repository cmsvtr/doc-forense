"""Triagem heurística: pontua documentos para priorizar a leitura (camada analítica).

Transparente por construção: cada ponto vem de um termo identificável, com página e trecho.
"""

import hashlib
import inspect
import re

from . import termos_cartel as T
from .caso import Caso, agora, escrever_json_atomico, ler_json
from .nomes import contar_empresas, e_contrato, emails_do_documento, empresas, pessoas, tipo_comunicacao
from .sei import localizador
from .texto import normalizar, trecho

_COMPILADOS = {
    cat: [(re.compile(padrao), padrao, peso) for padrao, peso in termos]
    for cat, termos in T.CATEGORIAS.items()
}


def hash_termos() -> str:
    return hashlib.sha256(inspect.getsource(T).encode("utf-8")).hexdigest()[:16]


def triar_documento(doc: dict, trechos_por_termo: int = 2) -> dict:
    categorias: dict[str, list] = {}
    pontos = 0
    textos = [(pg["n"], pg.get("texto") or "") for pg in doc["paginas"]]
    textos = [(n, original, normalizar(original)) for n, original in textos]
    for cat, termos in _COMPILADOS.items():
        achados_cat = []
        for regex, padrao, peso in termos:
            ocorrencias, paginas, trechos = 0, [], []
            for n, original, norm in textos:
                for m in regex.finditer(norm):
                    ocorrencias += 1
                    if n not in paginas:
                        paginas.append(n)
                    if len(trechos) < trechos_por_termo:
                        trechos.append({"pagina": n, "posicao": m.start(), "termo": original[m.start():m.end()],
                                        "trecho": trecho(original, m.start(), m.end())})
            if ocorrencias:
                contribuicao = min(ocorrencias, T.MAX_OCORRENCIAS_POR_TERMO) * peso
                pontos += contribuicao
                achados_cat.append({"padrao": padrao, "peso": peso, "ocorrencias": ocorrencias,
                                    "pontos": contribuicao, "paginas": paginas, "trechos": trechos})
        if achados_cat:
            categorias[cat] = sorted(achados_cat, key=lambda a: -a["pontos"])

    ent = doc.get("entidades") or {}
    bonus = []
    cnpjs = {c["valor"] for c in ent.get("cnpjs", [])}
    if len(cnpjs) >= 2:
        pontos += T.BONUS_CNPJS_DISTINTOS
        bonus.append(f"{len(cnpjs)} CNPJs distintos (+{T.BONUS_CNPJS_DISTINTOS})")
    dominios = {e["valor"].split("@")[1] for e in ent.get("emails", [])} - T.DOMINIOS_GENERICOS
    if len(dominios) >= 2:
        pontos += T.BONUS_DOMINIOS_DISTINTOS
        bonus.append(f"e-mails de {len(dominios)} domínios ({', '.join(sorted(dominios)[:4])}) (+{T.BONUS_DOMINIOS_DISTINTOS})")

    palavras = sum(len((pg.get("texto") or "").split()) for pg in doc["paginas"])

    texto_todo = "\n".join(original for _, original, _ in textos)
    msgs = emails_do_documento(doc)
    lista_empresas = sorted(empresas(texto_todo))
    lista_pessoas = sorted(pessoas(texto_todo, msgs))
    motivos = []
    if T.PRIORIZAR_EMAILS and msgs:
        motivos.append(f"e-mail ({len(msgs)} mensagem(ns))")
    comunicacao = tipo_comunicacao(doc)
    if T.PRIORIZAR_COMUNICACOES and comunicacao and comunicacao != "e-mail":
        motivos.append(f"comunicação ({comunicacao})")
    contrato = e_contrato(doc)
    if T.PRIORIZAR_CONTRATOS and contrato:
        motivos.append("contrato")
    n_empresas = contar_empresas(set(lista_empresas))
    if n_empresas >= T.PRIORIDADE_MIN_EMPRESAS:
        motivos.append(f"{n_empresas} empresas")
    if len(lista_pessoas) >= T.PRIORIDADE_MIN_PESSOAS:
        motivos.append(f"{len(lista_pessoas)} pessoas")
    return {
        "prioritario": bool(motivos),
        "tipo_comunicacao": comunicacao,
        "contrato": contrato,
        "motivos_prioridade": motivos,
        "empresas_citadas": lista_empresas[:30],
        "pessoas_citadas": lista_pessoas[:30],
        "documento_id": doc["documento_id"],
        "arquivo": doc["arquivo"]["nome"],
        "caminho": doc["arquivo"]["caminhos"][0],
        "localizador": localizador(doc),
        "pontuacao": pontos,
        "densidade_por_mil_palavras": round(pontos * 1000 / palavras, 1) if palavras else 0.0,
        "categorias": categorias,
        "bonus": bonus,
        "palavras": palavras,
    }


def triar_caso(caso: Caso) -> dict:
    resultados = [triar_documento(d) for d in caso.documentos()]
    # primeiro os prioritários (e-mail, contrato, 2+ empresas, 2+ pessoas); dentro de cada grupo, pela pontuação
    resultados.sort(key=lambda r: (not r["prioritario"], -r["pontuacao"], r["arquivo"].lower()))
    for i, r in enumerate(resultados, 1):
        r["posicao"] = i
    saida = {
        "schema": "doc-forense/triagem@1",
        "gerado_em": agora(),
        "termos_hash": hash_termos(),
        "aviso": "Ordem para priorizar a leitura: primeiro e-mails e outras comunicações, contratos e documentos com 2+ empresas ou "
                 "2+ pessoas; depois os demais; em cada grupo, pela pontuação de termos. Não indica nem comprova conduta.",
        "documentos": resultados,
    }
    escrever_json_atomico(caso.analise / "triagem.json", saida)
    caso.registrar("triagem_gerada", documentos=len(resultados), termos_hash=saida["termos_hash"])
    return saida


def ler_triagem(caso: Caso) -> dict | None:
    p = caso.analise / "triagem.json"
    return ler_json(p) if p.exists() else None
