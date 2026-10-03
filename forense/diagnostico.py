"""Verifica se o ambiente está pronto. Usado pelo instalador e pela interface."""

import platform
import sys

from .indice import fts5_disponivel
from .ocr import localizar_tessdata, localizar_tesseract, versao_tesseract


def diagnosticar(idioma: str = "por") -> list[tuple[str, bool, str]]:
    itens = []
    itens.append(("Python", sys.version_info >= (3, 11), platform.python_version()))
    exe = localizar_tesseract()
    itens.append(("Tesseract", bool(exe), f"{versao_tesseract(exe)} ({exe})" if exe else "não encontrado"))
    tessdata = localizar_tessdata(idioma)
    itens.append((f"Idioma do OCR ({idioma})", bool(tessdata), str(tessdata) if tessdata else f"{idioma}.traineddata não encontrado"))
    itens.append(("Busca de texto (SQLite FTS5)", fts5_disponivel(), "ok" if fts5_disponivel() else "indisponível; busca simples será usada"))
    for mod in ("pypdfium2", "pytesseract", "bs4", "docx", "streamlit"):
        try:
            __import__(mod)
            itens.append((f"Biblioteca {mod}", True, "ok"))
        except ImportError as e:
            itens.append((f"Biblioteca {mod}", False, str(e)))
    return itens


def imprimir() -> bool:
    itens = diagnosticar()
    for nome, ok, detalhe in itens:
        print(f"  [{'OK' if ok else 'FALHA'}] {nome}: {detalhe}")
    criticos = [i for i in itens if not i[1] and not i[0].startswith("Busca")]
    return not criticos
