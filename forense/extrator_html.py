"""Extração de HTML, incluindo cabeçalhos de e-mails exportados (De/Para/Data/Assunto)."""

import re
from email.utils import parsedate_to_datetime
from pathlib import Path

from .regex_br import extrair_datas
from .texto import limpar_quebras

_CAMPOS = {
    "de": "de", "from": "de",
    "para": "para", "to": "para",
    "cc": "cc",
    "enviado em": "data", "enviada em": "data", "enviado": "data", "sent": "data",
    "data": "data", "date": "data",
    "assunto": "assunto", "subject": "assunto",
}
_CABECALHO_RE = re.compile(
    r"^\s*(" + "|".join(sorted(map(re.escape, _CAMPOS), key=len, reverse=True)) + r")\s*:\s*(.*)$",
    re.IGNORECASE,
)
_HORA_RE = re.compile(r"\b([01]?\d|2[0-3])[:h]([0-5]\d)\b")


def interpretar_data(bruto: str) -> str | None:
    """Converte a data de um cabeçalho de e-mail para ISO (AAAA-MM-DD ou AAAA-MM-DDTHH:MM)."""
    bruto = bruto.strip()
    try:
        dt = parsedate_to_datetime(bruto)
        if dt:
            return dt.strftime("%Y-%m-%dT%H:%M")
    except (TypeError, ValueError, IndexError):
        pass
    datas = [d for d in extrair_datas(bruto) if d["precisao"] == "dia"]
    if not datas:
        return None
    iso = datas[0]["data"]
    hora = _HORA_RE.search(bruto[datas[0]["fim"]:])
    return f"{iso}T{int(hora.group(1)):02d}:{hora.group(2)}" if hora else iso


def extrair_cabecalhos_email(texto: str) -> list[dict]:
    """Encontra blocos de cabeçalho (um por mensagem, inclusive respostas e encaminhamentos)."""
    linhas = texto.split("\n")
    mensagens: list[dict] = []
    atual: dict = {}
    ultima_linha_cabecalho = -10

    def fechar():
        if atual.get("de") and (atual.get("data_bruta") or atual.get("assunto")):
            mensagens.append(dict(atual))

    i = 0
    while i < len(linhas):
        m = _CABECALHO_RE.match(linhas[i])
        if m:
            campo = _CAMPOS[m.group(1).lower()]
            valor = m.group(2).strip()
            # Em HTML convertido, o valor costuma vir na linha seguinte ("<b>De:</b> Fulano").
            if not valor and i + 1 < len(linhas) and not _CABECALHO_RE.match(linhas[i + 1]):
                valor = linhas[i + 1].strip()
                i += 1
            if i - ultima_linha_cabecalho > 3 or (campo == "de" and "de" in atual):
                fechar()
                atual = {}
            chave = "data_bruta" if campo == "data" else campo
            if chave not in atual and valor:
                atual[chave] = valor
            ultima_linha_cabecalho = i
        i += 1
    fechar()

    for msg in mensagens:
        if msg.get("data_bruta"):
            msg["data_iso"] = interpretar_data(msg["data_bruta"])
    return mensagens


def extrair_html(caminho: Path, parametros: dict) -> dict:
    from bs4 import BeautifulSoup

    bruto = caminho.read_bytes()
    sopa = BeautifulSoup(bruto, "html.parser")
    titulo = sopa.title.get_text(strip=True) if sopa.title else None
    for tag in sopa(["script", "style", "noscript", "template"]):
        tag.decompose()
    for br in sopa.find_all("br"):
        br.replace_with("\n")
    texto = limpar_quebras(sopa.get_text(separator="\n"))
    texto = re.sub(r"\n[ \t]+", "\n", texto)

    return {
        "paginas": [{"n": 1, "metodo": "html", "texto": texto, "caracteres": len(texto)}],
        "erros": [],
        "html": {"titulo": titulo, "codificacao_detectada": sopa.original_encoding},
        "emails": extrair_cabecalhos_email(texto),
    }
