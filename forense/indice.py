"""Índice SQLite com busca de texto completo (FTS5), sem distinção de acentos.

É descartável: sempre pode ser reconstruído a partir dos JSON da camada bruta.
"""

import os
import re
import sqlite3
import tempfile
from contextlib import closing

from .caso import Caso, substituir
from .sei import localizador

# hífen no fim da linha, admitindo uma linha em branco no meio (comum no HTML convertido)
_HIFEN_FIM_DE_LINHA = re.compile(r"(\w)-[ \t]*\n(?:[ \t]*\n)?[ \t]*(\w)")


def desfazer_hifenizacao(texto: str) -> str:
    """«circulari-\\nzar» -> «circularizar»: sem isso a busca perde a palavra onde o PDF a quebrou."""
    return _HIFEN_FIM_DE_LINHA.sub(r"\1\2", texto)


# Mudou o esquema das tabelas? Incremente: índices antigos são reconstruídos sozinhos.
INDICE_VERSAO = 2


def fts5_disponivel() -> bool:
    try:
        with closing(sqlite3.connect(":memory:")) as c:
            c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False


def reconstruir_indice(caso: Caso) -> int:
    fd, tmp = tempfile.mkstemp(dir=caso.raiz, prefix=".indice_", suffix=".sqlite")
    os.close(fd)
    fts = fts5_disponivel()
    n = 0
    try:
        with closing(sqlite3.connect(tmp)) as con:
            con.execute("""CREATE TABLE documentos (
                id TEXT PRIMARY KEY, nome TEXT, caminho TEXT, localizador TEXT, tipo TEXT, status TEXT,
                n_paginas INTEGER, n_paginas_ocr INTEGER, confianca_min REAL, alertas INTEGER)""")
            if fts:
                con.execute("CREATE VIRTUAL TABLE paginas USING fts5("
                            "doc_id UNINDEXED, pagina UNINDEXED, texto, tokenize='unicode61 remove_diacritics 2')")
            else:
                con.execute("CREATE TABLE paginas (doc_id TEXT, pagina INTEGER, texto TEXT)")
            con.execute("CREATE TABLE entidades (doc_id TEXT, tipo TEXT, valor TEXT, paginas TEXT)")
            con.execute(f"PRAGMA user_version = {INDICE_VERSAO}")

            for d in caso.documentos():
                did = d["documento_id"]
                confs = [p["confianca_media"] for p in d["paginas"] if p.get("confianca_media") is not None]
                con.execute("INSERT INTO documentos VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    did, d["arquivo"]["nome"], d["arquivo"]["caminhos"][0], localizador(d), d["arquivo"]["tipo"], d["status"],
                    len(d["paginas"]), sum(1 for p in d["paginas"] if p["metodo"] == "ocr"),
                    min(confs) if confs else None, len(d["alertas"])))
                con.executemany("INSERT INTO paginas VALUES (?,?,?)",
                                [(did, p["n"], desfazer_hifenizacao(p.get("texto") or "")) for p in d["paginas"]])
                for tipo, itens in (d.get("entidades") or {}).items():
                    if tipo == "datas":
                        continue
                    con.executemany("INSERT INTO entidades VALUES (?,?,?,?)", [
                        (did, tipo, it["valor"], ",".join(map(str, it["paginas"]))) for it in itens])
                n += 1
            con.commit()
        substituir(tmp, caso.indice)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    caso.registrar("indice_reconstruido", documentos=n, fts5=fts)
    return n


def garantir_indice(caso: Caso) -> bool:
    """Reconstrói o índice se ele não existe ou é de uma versão anterior do aplicativo."""
    if not caso.extraido.is_dir() or not any(caso.extraido.glob("*.json")):
        return caso.indice.exists()
    if caso.indice.exists():
        try:
            with closing(sqlite3.connect(caso.indice)) as con:
                if con.execute("PRAGMA user_version").fetchone()[0] == INDICE_VERSAO:
                    return True
        except sqlite3.DatabaseError:
            pass
    reconstruir_indice(caso)
    return True


def _consulta_fts(texto: str) -> str:
    """Converte o que o usuário digitou numa consulta FTS5 segura.

    "frase exata" vira frase; palavra* vira prefixo; demais palavras são exigidas (E).
    OU entre termos: escreva OU (ou OR).
    """
    partes = []
    for frase, palavra in re.findall(r'"([^"]+)"|(\S+)', texto):
        if frase:
            partes.append('"' + frase.replace('"', "") + '"')
        elif palavra.upper() in ("OU", "OR"):
            partes.append("OR")
        else:
            prefixo = palavra.endswith("*")
            limpa = re.sub(r"[^\w\-./]", "", palavra.rstrip("*"))
            if limpa:
                partes.append('"' + limpa + '"' + ("*" if prefixo else ""))
    while partes and partes[-1] == "OR":
        partes.pop()
    while partes and partes[0] == "OR":
        partes.pop(0)
    return " ".join(partes)


def buscar(caso: Caso, texto: str, limite: int = 200) -> list[dict]:
    if not texto.strip() or not garantir_indice(caso):
        return []
    with closing(sqlite3.connect(caso.indice)) as con:
        con.row_factory = sqlite3.Row
        fts = con.execute("SELECT sql FROM sqlite_master WHERE name='paginas'").fetchone()[0].upper().find("FTS5") >= 0
        if fts:
            consulta = _consulta_fts(texto)
            if not consulta:
                return []
            linhas = con.execute("""
                SELECT d.nome, d.caminho, d.localizador, paginas.doc_id, paginas.pagina,
                       snippet(paginas, 2, '«', '»', ' … ', 30) AS trecho
                FROM paginas JOIN documentos d ON d.id = paginas.doc_id
                WHERE paginas MATCH ? ORDER BY bm25(paginas) LIMIT ?""", (consulta, limite)).fetchall()
        else:
            linhas = con.execute("""
                SELECT d.nome, d.caminho, d.localizador, p.doc_id, p.pagina, substr(p.texto, 1, 300) AS trecho
                FROM paginas p JOIN documentos d ON d.id = p.doc_id
                WHERE p.texto LIKE ? LIMIT ?""", (f"%{texto}%", limite)).fetchall()
        return [dict(l) for l in linhas]


def entidades_do_caso(caso: Caso) -> list[dict]:
    """Cada CNPJ/CPF/e-mail/valor com os documentos onde aparece."""
    if not garantir_indice(caso):
        return []
    with closing(sqlite3.connect(caso.indice)) as con:
        con.row_factory = sqlite3.Row
        linhas = con.execute("""
            SELECT e.tipo, e.valor, COUNT(DISTINCT e.doc_id) AS documentos,
                   GROUP_CONCAT(d.localizador || ', p. ' || e.paginas, '; ') AS onde
            FROM entidades e JOIN documentos d ON d.id = e.doc_id
            GROUP BY e.tipo, e.valor ORDER BY e.tipo, documentos DESC, e.valor""").fetchall()
        return [dict(l) for l in linhas]
