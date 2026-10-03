"""Localização e uso do Tesseract."""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ_APP = Path(__file__).resolve().parent.parent

_CAMINHOS_WINDOWS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]


def localizar_tesseract() -> str | None:
    """Caminho do executável: variável FORENSE_TESSERACT, PATH ou locais padrão do Windows."""
    candidato = os.environ.get("FORENSE_TESSERACT")
    if candidato and Path(candidato).is_file():
        return candidato
    no_path = shutil.which("tesseract")
    if no_path:
        return no_path
    if sys.platform.startswith("win"):
        for c in _CAMINHOS_WINDOWS:
            if Path(c).is_file():
                return c
    return None


def localizar_tessdata(idioma: str = "por") -> Path | None:
    """Pasta com <idioma>.traineddata. Prioriza a pasta tessdata do próprio aplicativo."""
    candidatos = []
    if os.environ.get("FORENSE_TESSDATA"):
        candidatos.append(Path(os.environ["FORENSE_TESSDATA"]))
    candidatos.append(RAIZ_APP / "tessdata")
    if os.environ.get("TESSDATA_PREFIX"):
        candidatos.append(Path(os.environ["TESSDATA_PREFIX"]))
    exe = localizar_tesseract()
    if exe:
        candidatos.append(Path(exe).resolve().parent / "tessdata")
    candidatos += [Path(p) for p in (
        "/usr/share/tesseract-ocr/5/tessdata", "/usr/share/tesseract-ocr/4.00/tessdata",
        "/usr/share/tessdata", "/usr/local/share/tessdata", "/opt/homebrew/share/tessdata",
    )]
    for c in candidatos:
        if (c / f"{idioma}.traineddata").is_file():
            return c
    return None


def versao_tesseract(exe: str | None = None) -> str | None:
    exe = exe or localizar_tesseract()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20)
        saida = (r.stdout or r.stderr).strip().splitlines()
        return saida[0] if saida else None
    except (OSError, subprocess.SubprocessError):
        return None


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def configurar_processo(idioma: str = "por") -> dict:
    """Prepara o processo atual para rodar OCR. Retorna a descrição das ferramentas usadas."""
    import pytesseract

    exe = localizar_tesseract()
    if not exe:
        raise RuntimeError("Tesseract não encontrado. Rode o instalador ou defina FORENSE_TESSERACT.")
    pytesseract.pytesseract.tesseract_cmd = exe
    tessdata = localizar_tessdata(idioma)
    if not tessdata:
        raise RuntimeError(f"Dados do idioma '{idioma}' ({idioma}.traineddata) não encontrados.")
    # Tesseract 4+: TESSDATA_PREFIX aponta para a própria pasta tessdata.
    # Usamos a variável em vez de --tessdata-dir porque caminhos com espaço quebram no Windows.
    os.environ["TESSDATA_PREFIX"] = str(tessdata)
    # Um processo por núcleo; cada Tesseract usa uma thread só.
    os.environ["OMP_THREAD_LIMIT"] = "1"
    return {
        "tesseract": versao_tesseract(exe),
        "idioma": idioma,
        "traineddata": str(tessdata / f"{idioma}.traineddata"),
        "traineddata_sha256": sha256_arquivo(tessdata / f"{idioma}.traineddata"),
    }


def texto_e_confianca_do_tsv(tsv: str) -> tuple[str, float | None, int]:
    """Reconstrói o texto das caixas do Tesseract (bloco, parágrafo, linha) e a confiança média."""
    linhas: list[str] = []
    atual: list[str] = []
    chave_anterior = None
    bloco_anterior = None
    confiancas: list[float] = []
    for linha in tsv.split("\n")[1:]:
        c = linha.split("\t")
        if len(c) < 12:
            continue
        palavra = c[11].strip()
        if not palavra:
            continue
        try:
            conf = float(c[10])
        except ValueError:
            conf = -1.0
        if conf >= 0:
            confiancas.append(conf)
        bloco = (c[2], c[3])
        chave = bloco + (c[4],)
        if chave != chave_anterior and atual:
            linhas.append(" ".join(atual))
            atual = []
            if bloco != bloco_anterior:
                linhas.append("")
        atual.append(palavra)
        chave_anterior, bloco_anterior = chave, bloco
    if atual:
        linhas.append(" ".join(atual))
    texto = "\n".join(linhas).strip()
    media = round(sum(confiancas) / len(confiancas), 1) if confiancas else None
    return texto, media, len(confiancas)


def ocr_imagem(imagem, idioma: str = "por") -> tuple[str, float | None, int, str]:
    """OCR de uma imagem PIL. Retorna (texto, confiança média 0-100, nº de palavras, TSV bruto).

    O TSV guarda a caixa de cada palavra: permite localizar uma citação na página sem refazer
    o OCR e é o formato que a skill sg-nt:instrucao reaproveita (_caixas/<arquivo>/pNNNN.tsv).
    """
    import pytesseract

    tsv = pytesseract.image_to_data(imagem.convert("L"), lang=idioma, config="--psm 3")
    texto, media, palavras = texto_e_confianca_do_tsv(tsv)
    return texto, media, palavras, tsv
