"""Utilidades de texto."""

import re
import unicodedata


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos, preservando o comprimento.

    Cada caractere vira exatamente um caractere, então posições encontradas no
    texto normalizado valem também no texto original (usado para recortar trechos).
    """
    saida = []
    for c in texto:
        base = unicodedata.normalize("NFD", c)[0].lower()
        saida.append(base if len(base) == 1 else c)
    return "".join(saida)


def limpar_quebras(texto: str) -> str:
    """Padroniza quebras de linha e remove excesso de linhas em branco."""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    texto = re.sub(r"[ \t ]+\n", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def trecho(texto: str, inicio: int, fim: int, margem: int = 120) -> str:
    """Recorta o contexto em volta de [inicio, fim) numa única linha."""
    a = max(0, inicio - margem)
    b = min(len(texto), fim + margem)
    recorte = " ".join(texto[a:b].split())
    return ("…" if a > 0 else "") + recorte + ("…" if b < len(texto) else "")


def contar_alfanumericos(texto: str) -> int:
    return sum(1 for c in texto if c.isalnum())
