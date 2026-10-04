"""Identificação de documentos exportados do SEI e forma canônica de citá-los.

Regras herdadas da skill sg-nt:instrucao (lições de casos reais):
- o número SEI está no nome do arquivo («[588]-1215707_E_mail.pdf»: ordem 588, SEI 1215707);
- o arquivo de pasta de anexo extraída herda o SEI da pasta («[104]-1157123_Anexo/Ata.pdf»);
- o documento de dentro pode ter outro SEI, no cabeçalho («SEI/CADE - 1197874 - Nota Técnica»);
- o tipo no nome só é confiável no HTML, que nasce no SEI. No PDF é o tipo que quem protocolou
  escolheu: defesa protocolada como «E-mail» é comum.
"""

import re
from pathlib import PurePosixPath

_ID_RE = re.compile(r"(?<!\d)(\d{6,7})(?!\d)")
# Números de processo contêm 6-7 dígitos que NÃO são SEI: «08700.007351/2015-51» (processo
# administrativo; no nome de pasta vem com «_» ou «-») e «0001234-56.2024.8.26.0100» (CNJ).
_PROCESSO_RE = re.compile(
    r"\d{5}\.?\d{6}[/_.\-]?\d{4}[/_.\-]?\d{2}"
    r"|\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}")
# «Doc. 12.pdf», «Documento 12», «DOC 3» dentro de pasta de anexo: o Documento N do anexo.
_DOC_N_RE = re.compile(r"^\s*doc(?:umento)?\.?\s*n?[º°o.]?\s*(\d{1,4})\b", re.IGNORECASE)

_NOME_SEI_RE = re.compile(r"^\[(\d+)\]\s*-\s*(\d{6,7})[_\s-]+(.+)$")
_CABECALHO_RE = re.compile(r"SEI/\w+\s*-\s*(\d{6,7})\s*-\s*([^\n]{0,80})")
_ATO_RE = re.compile(
    r"\b(NOTA T[ÉE]CNICA|DESPACHO|PARECER|OF[ÍI]CIO|DECIS[ÃA]O|NOTA INFORMATIVA)"
    r"(?:\s+\w+)?\s+N[º°o.]+\s*(\d{1,5}/\d{4})", re.IGNORECASE)


def _ids(texto: str) -> list[str]:
    """Números de 6-7 dígitos do texto, sem os que fazem parte de número de processo."""
    return _ID_RE.findall(_PROCESSO_RE.sub(" ", texto))


def _tipo_legivel(bruto: str) -> str:
    t = re.sub(r"[_]+", " ", bruto).strip()
    t = re.sub(r"\s+\d+(\s+\d{4})?$", "", t)  # «Nota Tecnica Confidencial 14 2023» -> sem o número
    return t


def identificar(caminho_relativo: str, extensao: str, texto_inicio: str) -> dict | None:
    """Dados SEI de um documento, ou None se nada indica origem no SEI.

    caminho_relativo: caminho dentro da pasta de originais (com «/»).
    texto_inicio: texto das primeiras páginas.
    """
    p = PurePosixPath(caminho_relativo)
    info: dict = {}
    m = _NOME_SEI_RE.match(p.stem)
    if m:
        info.update(ordem_arvore=int(m.group(1)), numero=m.group(2), fonte="nome do arquivo",
                    tipo_no_nome=_tipo_legivel(m.group(3)))
    else:
        ids = _ids(p.stem)
        if ids:
            info.update(numero=ids[0], fonte="nome do arquivo")
        else:
            # o arquivo de pasta de anexo herda o SEI da pasta mais próxima que o tenha
            for i in range(len(p.parts) - 2, -1, -1):
                ids = _ids(p.parts[i])
                if ids:
                    info.update(numero=ids[0], fonte="pasta de anexo",
                                anexo=PurePosixPath(*p.parts[i + 1:]).as_posix())
                    doc_n = _DOC_N_RE.match(p.stem)
                    if doc_n:
                        info["documento_n"] = int(doc_n.group(1))
                    break

    cab = texto_inicio[:4000]
    internos = sorted(set(_CABECALHO_RE.findall(cab)), key=lambda x: cab.find(x[0]))
    if internos:
        info["numero_no_cabecalho"] = internos[0][0]
        info["titulo_no_cabecalho"] = internos[0][1].strip()
        if "numero" not in info:
            info.update(numero=internos[0][0], fonte="cabeçalho")
    ato = _ATO_RE.search(cab)
    if ato:
        info["numero_ato"] = ato.group(2)
        info["especie_ato"] = ato.group(1).upper()

    if not info.get("numero"):
        return None
    if "tipo_no_nome" in info:
        info["tipo_no_nome_confiavel"] = extensao in (".html", ".htm")
    return info


def localizador(doc: dict, paginas=None) -> str:
    """Forma de citar: «SEI nº 1215707, p. 3» quando há SEI; senão o nome do arquivo."""
    sei = doc.get("sei") or {}
    base = f"SEI nº {sei['numero']}" if sei.get("numero") else doc["arquivo"]["nome"]
    if sei.get("documento_n"):
        base += f", Doc. {sei['documento_n']}"
    elif sei.get("anexo"):
        base += f" ({sei['anexo']})"
    if paginas:
        lista = paginas if isinstance(paginas, (list, tuple)) else [paginas]
        base += (", p. " if len(lista) == 1 else ", pp. ") + ", ".join(map(str, lista))
    return base
