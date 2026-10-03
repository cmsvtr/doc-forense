"""Triagem heurística: pontua documentos para priorizar a leitura (camada analítica).

Transparente por construção: cada ponto vem de um termo identificável, com página e trecho.
"""

import hashlib
import inspect
import re

from . import termos_cartel as T
from .caso import Caso, agora, escrever_json_atomico, ler_json
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
    return {
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
    resultados.sort(key=lambda r: (-r["pontuacao"], r["arquivo"].lower()))
    for i, r in enumerate(resultados, 1):
        r["posicao"] = i
    saida = {
        "schema": "doc-forense/triagem@1",
        "gerado_em": agora(),
        "termos_hash": hash_termos(),
        "aviso": "Pontuação heurística para priorizar leitura. Não indica nem comprova conduta.",
        "documentos": resultados,
    }
    escrever_json_atomico(caso.analise / "triagem.json", saida)
    caso.registrar("triagem_gerada", documentos=len(resultados), termos_hash=saida["termos_hash"])
    return saida


def ler_triagem(caso: Caso) -> dict | None:
    p = caso.analise / "triagem.json"
    return ler_json(p) if p.exists() else None
