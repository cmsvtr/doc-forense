"""Conferência de citações: o trecho que a IA diz ter lido existe mesmo no documento?

É a principal defesa contra alucinação. A IA é obrigada a copiar o trecho literal de cada achado;
aqui a máquina o procura no texto das páginas. Achou: o achado ganha a página e o trecho *como
está no documento* (não como a IA o escreveu). Não achou: o achado é descartado.

A comparação ignora acentos, maiúsculas, pontuação, espaços e hifenização de fim de linha, que
variam entre o texto extraído (sobretudo o OCR) e a cópia feita pelo modelo.
"""

import difflib
import re
import unicodedata

# Semelhança mínima para aceitar uma citação que não bate letra por letra (OCR, um acento trocado).
SIMILARIDADE_MINIMA = 0.90
PALAVRAS_MINIMAS = 3  # citação curta demais («a empresa») acha-se em qualquer lugar e não prova nada


def _tokens_com_posicao(texto: str) -> list[tuple[str, int, int]]:
    """Palavras normalizadas (minúsculas, sem acento) com a posição no texto original."""
    # hifenização de fim de linha («circulari-\nzar») conta como uma palavra só; a marcação
    # preserva o comprimento, para as posições continuarem valendo no texto original
    marcado = re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=\w)", lambda m: "\x00" * len(m.group(0)), texto)
    saida = []
    for m in re.finditer(r"[^\W_]+(?:\x00+[^\W_]+)*", marcado):
        palavra = m.group(0).replace("\x00", "")
        base = "".join(c for c in unicodedata.normalize("NFD", palavra.lower()) if not unicodedata.combining(c))
        saida.append((base, m.start(), m.end()))
    return saida


def _normalizar_citacao(citacao: str) -> list[str]:
    return [t for t, _, _ in _tokens_com_posicao(citacao)]


def localizar(citacao: str, paginas: list[dict]) -> dict | None:
    """Procura a citação nas páginas ({"n", "texto"}). Retorna
    {"pagina", "inicio", "fim", "trecho_fonte", "similaridade", "literal"} ou None."""
    alvo = _normalizar_citacao(citacao or "")
    if len(alvo) < PALAVRAS_MINIMAS:
        return None
    melhor = None
    for pg in paginas:
        texto = pg.get("texto") or ""
        toks = _tokens_com_posicao(texto)
        palavras = [t for t, _, _ in toks]
        n = len(alvo)
        if len(palavras) < n:
            continue
        # 1) literal (normalizado)
        for i in range(len(palavras) - n + 1):
            if palavras[i:i + n] == alvo:
                ini, fim = toks[i][1], toks[i + n - 1][2]
                return {"pagina": pg["n"], "inicio": ini, "fim": fim, "trecho_fonte": texto[ini:fim],
                        "similaridade": 1.0, "literal": True}
        # 2) aproximada: janela do mesmo tamanho (±1 palavra) com maior semelhança
        conjunto = set(alvo)
        for tam in (n, n - 1, n + 1):
            if tam < PALAVRAS_MINIMAS or tam > len(palavras):
                continue
            for i in range(len(palavras) - tam + 1):
                janela = palavras[i:i + tam]
                if len(conjunto.intersection(janela)) < n * 0.6:  # poda barata antes da comparação fina
                    continue
                r = difflib.SequenceMatcher(None, " ".join(alvo), " ".join(janela), autojunk=False).ratio()
                if r >= SIMILARIDADE_MINIMA and (melhor is None or r > melhor["similaridade"]):
                    ini, fim = toks[i][1], toks[i + tam - 1][2]
                    melhor = {"pagina": pg["n"], "inicio": ini, "fim": fim, "trecho_fonte": texto[ini:fim],
                              "similaridade": round(r, 3), "literal": False}
    return melhor


def aparece(termo: str, texto: str) -> bool:
    """O termo (nome, empresa) aparece no texto, ignorando acentos, maiúsculas e pontuação?"""
    alvo = _normalizar_citacao(termo or "")
    if not alvo:
        return False
    palavras = [t for t, _, _ in _tokens_com_posicao(texto or "")]
    n = len(alvo)
    return any(palavras[i:i + n] == alvo for i in range(len(palavras) - n + 1))
