"""Extração de arquivos de texto (.txt): conversas exportadas do WhatsApp, e-mails salvos como texto.

O texto não tem páginas; para a citação continuar localizável, ele é partido em «páginas» de
LINHAS_POR_PAGINA linhas, e cada uma registra o intervalo de linhas que cobre.
"""

from pathlib import Path

from .extrator_html import extrair_cabecalhos_email
from .texto import limpar_quebras

LINHAS_POR_PAGINA = 150


def ler_texto(caminho: Path) -> tuple[str, str]:
    """(texto, codificação): UTF-8 (com ou sem BOM), senão Windows-1252, que nunca falha."""
    bruto = caminho.read_bytes()
    for cod in ("utf-8-sig", "cp1252"):
        try:
            return bruto.decode(cod), cod
        except UnicodeDecodeError:
            continue
    return bruto.decode("latin-1"), "latin-1"


def extrair_txt(caminho: Path, parametros: dict) -> dict:
    texto, codificacao = ler_texto(caminho)
    linhas = texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    paginas = []
    for i in range(0, max(len(linhas), 1), LINHAS_POR_PAGINA):
        bloco = limpar_quebras("\n".join(linhas[i:i + LINHAS_POR_PAGINA]))
        paginas.append({"n": len(paginas) + 1, "metodo": "texto", "texto": bloco, "caracteres": len(bloco),
                        "linhas": [i + 1, min(i + LINHAS_POR_PAGINA, len(linhas))]})
    return {"paginas": paginas, "erros": [], "texto_simples": {"codificacao": codificacao, "linhas": len(linhas)},
            "emails": extrair_cabecalhos_email("\n".join(linhas[:400]))}
