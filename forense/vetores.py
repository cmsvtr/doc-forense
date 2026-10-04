"""Busca por significado (vetores) combinada com a busca por palavra.

Acha passagens que não usam as palavras da pergunta («o pessoal do norte», «acerto da tabela»).
Os vetores vêm do próprio Ollama (modelo bge-m3), sem PyTorch, e ficam em vetores.sqlite:
descartável, reconstruível a partir da camada bruta, e incremental (só o que mudou é refeito).

Cada passagem tem até ~250 palavras e nunca atravessa páginas, para a citação ser exata. Antes de
virar vetor, ganha um cabeçalho com o SEI, o título e a página: a versão barata do «Contextual
Retrieval» da Anthropic (o contexto do documento entra no vetor sem chamar o LLM por passagem).
"""

import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing

import numpy as np

from . import ia
from .caso import Caso, agora
from .sei import localizador

MODELO_VETORES = os.environ.get("FORENSE_MODELO_VETORES", "bge-m3")
PALAVRAS_POR_PASSAGEM = 250
SOBREPOSICAO = 40     # palavras repetidas entre passagens vizinhas: frase cortada no meio não se perde
LOTE = 16             # passagens por chamada ao Ollama
RRF_K = 60            # constante da fusão de rankings (Reciprocal Rank Fusion)


def caminho(caso: Caso):
    return caso.raiz / "vetores.sqlite"


def passagens(doc: dict) -> list[dict]:
    """Passagens de uma página por vez, com sobreposição, guardando a posição no texto da página."""
    saida = []
    for pg in doc["paginas"]:
        texto = pg.get("texto") or ""
        palavras = [(m.start(), m.end()) for m in re.finditer(r"\S+", texto)]
        if not palavras:
            continue
        passo = PALAVRAS_POR_PASSAGEM - SOBREPOSICAO
        for i in range(0, len(palavras), passo):
            fatia = palavras[i:i + PALAVRAS_POR_PASSAGEM]
            ini, fim = fatia[0][0], fatia[-1][1]
            saida.append({"pagina": pg["n"], "inicio": ini, "fim": fim, "texto": texto[ini:fim]})
            if i + PALAVRAS_POR_PASSAGEM >= len(palavras):
                break
    return saida


def cabecalho(doc: dict, pagina: int) -> str:
    sei = doc.get("sei") or {}
    partes = [localizador(doc, [pagina])]
    for campo in ("titulo_no_cabecalho", "tipo_no_nome"):
        if sei.get(campo):
            partes.append(sei[campo])
    if (doc.get("html") or {}).get("titulo"):
        partes.append(doc["html"]["titulo"])
    return "Documento: " + " · ".join(partes)


def _abrir(caso: Caso) -> sqlite3.Connection:
    con = sqlite3.connect(caminho(caso))
    con.execute("""CREATE TABLE IF NOT EXISTS documentos (
        doc_id TEXT PRIMARY KEY, chave TEXT, passagens INTEGER, atualizado_em TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS passagens (
        doc_id TEXT, n INTEGER, pagina INTEGER, inicio INTEGER, fim INTEGER, texto TEXT, vetor BLOB,
        PRIMARY KEY (doc_id, n))""")
    return con


def _vetorizar(textos: list[str], modelo: str) -> np.ndarray:
    r = ia._pedir("/api/embed", {"model": modelo, "input": textos, "keep_alive": "30m"}, tempo=900)
    v = np.asarray(r["embeddings"], dtype=np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)


def situacao(caso: Caso) -> dict:
    total = len(caso.documentos())
    if not caminho(caso).exists():
        return {"documentos": 0, "total": total, "passagens": 0}
    with closing(_abrir(caso)) as con:
        d, p = con.execute("SELECT COUNT(*), COALESCE(SUM(passagens), 0) FROM documentos").fetchone()
    return {"documentos": d, "total": total, "passagens": p}


def indexar(caso: Caso, modelo: str = MODELO_VETORES, log=print, progresso=None) -> dict:
    """Gera os vetores do que ainda não tem (ou mudou). Interrompido, continua de onde parou."""
    docs = caso.documentos()
    feitos = 0
    with closing(_abrir(caso)) as con:
        atuais = dict(con.execute("SELECT doc_id, chave FROM documentos").fetchall())
        validos = {d["documento_id"] for d in docs}
        for velho in set(atuais) - validos:  # documento que saiu do caso
            con.execute("DELETE FROM passagens WHERE doc_id = ?", (velho,))
            con.execute("DELETE FROM documentos WHERE doc_id = ?", (velho,))
        con.commit()
        for k, doc in enumerate(docs, 1):
            chave = hashlib.sha256(json.dumps(
                [modelo, PALAVRAS_POR_PASSAGEM, SOBREPOSICAO, cabecalho(doc, 0),
                 [p.get("texto") or "" for p in doc["paginas"]]], ensure_ascii=False).encode()).hexdigest()[:16]
            if atuais.get(doc["documento_id"]) == chave:
                continue
            ps = passagens(doc)
            vetores = []
            for i in range(0, len(ps), LOTE):
                lote = ps[i:i + LOTE]
                vetores.append(_vetorizar([cabecalho(doc, p["pagina"]) + "\n" + p["texto"] for p in lote], modelo))
            matriz = np.vstack(vetores) if vetores else np.zeros((0, 1), dtype=np.float32)
            con.execute("DELETE FROM passagens WHERE doc_id = ?", (doc["documento_id"],))
            con.executemany("INSERT INTO passagens VALUES (?,?,?,?,?,?,?)", [
                (doc["documento_id"], n, p["pagina"], p["inicio"], p["fim"], p["texto"], matriz[n].tobytes())
                for n, p in enumerate(ps)])
            con.execute("INSERT OR REPLACE INTO documentos VALUES (?,?,?,?)",
                        (doc["documento_id"], chave, len(ps), agora()))
            con.commit()
            feitos += 1
            log(f"  [{k}/{len(docs)}] {doc['arquivo']['nome']}: {len(ps)} passagem(ns)")
            if progresso:
                progresso(k, len(docs), doc["arquivo"]["nome"])
    caso.registrar("vetores_indexados", modelo=modelo, documentos_refeitos=feitos)
    return {"documentos_refeitos": feitos, **situacao(caso)}


def buscar_por_significado(caso: Caso, pergunta: str, limite: int = 50, modelo: str = MODELO_VETORES) -> list[dict]:
    if not caminho(caso).exists():
        return []
    q = _vetorizar([pergunta], modelo)[0]
    with closing(_abrir(caso)) as con:
        linhas = con.execute("SELECT doc_id, n, pagina, inicio, fim, texto, vetor FROM passagens").fetchall()
    if not linhas:
        return []
    matriz = np.frombuffer(b"".join(l[6] for l in linhas), dtype=np.float32).reshape(len(linhas), -1)
    notas = matriz @ q
    ordem = np.argsort(-notas)[:limite]
    return [{"doc_id": linhas[i][0], "pagina": linhas[i][2], "inicio": linhas[i][3], "fim": linhas[i][4],
             "texto": linhas[i][5], "similaridade": float(notas[i])} for i in ordem]


_VAZIAS = set("""
a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela pelos pelas para com sem sob
sobre entre ate e ou que qual quais quem quando onde como porque se ja nao mais menos muito muita foi
foram ser sao era eram tem teve ha houve isso isto esse essa este esta aquele aquela seu sua seus suas
""".split())


def consulta_por_palavras(pergunta: str) -> str:
    """Pergunta em linguagem natural -> consulta OU com as palavras significativas (busca por palavra)."""
    from .texto import normalizar

    termos = [t for t in re.findall(r"[^\W_]+", pergunta) if len(t) >= 4 and normalizar(t) not in _VAZIAS]
    return " OU ".join(dict.fromkeys(termos))


def _janela(texto: str, pergunta: str) -> str:
    """~PALAVRAS_POR_PASSAGEM palavras em volta da primeira palavra da pergunta achada na página."""
    from .texto import normalizar

    palavras = texto.split()
    alvos = {normalizar(t)[:6] for t in re.findall(r"[^\W_]+", pergunta) if len(t) >= 4}
    idx = next((i for i, w in enumerate(palavras) if normalizar(w)[:6] in alvos), 0)
    ini = max(0, idx - PALAVRAS_POR_PASSAGEM // 3)
    return " ".join(palavras[ini:ini + PALAVRAS_POR_PASSAGEM])


def buscar_hibrida(caso: Caso, pergunta: str, limite: int = 20) -> list[dict]:
    """Funde a busca por palavra (por página) e a por significado (por passagem) com RRF.
    Cada resultado é uma página, com a melhor passagem dela e de onde veio (palavra, significado)."""
    from .indice import buscar

    resultados: dict[tuple, dict] = {}

    def somar(chave, posicao, origem, dados):
        r = resultados.setdefault(chave, {"pontos": 0.0, "origens": set(), **dados})
        r["pontos"] += 1.0 / (RRF_K + posicao)
        r["origens"].add(origem)
        for campo, valor in dados.items():
            r.setdefault(campo, valor)

    consulta = consulta_por_palavras(pergunta)
    for pos, r in enumerate(buscar(caso, consulta, limite=50) if consulta else [], 1):
        somar((r["doc_id"], r["pagina"]), pos, "palavra",
              {"doc_id": r["doc_id"], "pagina": r["pagina"], "trecho_palavra": r["trecho"]})
    try:
        semanticos = buscar_por_significado(caso, pergunta)
    except Exception:  # Ollama fora do ar: fica só a busca por palavra
        semanticos = []
    vistos = set()
    for pos, r in enumerate(semanticos, 1):
        chave = (r["doc_id"], r["pagina"])
        if chave in vistos:  # uma página conta uma vez, pela melhor passagem
            continue
        vistos.add(chave)
        somar(chave, pos, "significado", {"doc_id": r["doc_id"], "pagina": r["pagina"], "passagem": r["texto"],
                                          "similaridade": r["similaridade"]})

    por_id = {d["documento_id"]: d for d in caso.documentos()}
    saida = []
    for r in sorted(resultados.values(), key=lambda x: -x["pontos"])[:limite]:
        doc = por_id.get(r["doc_id"])
        if not doc:
            continue
        r["origens"] = sorted(r["origens"])
        r["localizador"] = localizador(doc, [r["pagina"]])
        r["caminho"] = doc["arquivo"]["caminhos"][0]
        if "passagem" not in r:  # veio só da busca por palavra: recorta em volta do termo achado
            texto = next((p.get("texto") or "" for p in doc["paginas"] if p["n"] == r["pagina"]), "")
            r["passagem"] = _janela(texto, pergunta)
        saida.append(r)
    return saida
