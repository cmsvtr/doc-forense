"""Abre um documento original no programa do computador, de preferência já na página citada.

Navegadores não seguem links file:// vindos de uma página web; por isso o aplicativo pede ao
sistema que abra o arquivo. Só abre arquivos de dentro da pasta de originais do caso.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

_NAVEGADORES_WINDOWS = [
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
]


def navegador_com_pdf() -> str | None:
    """Edge ou Chrome: o leitor de PDF deles aceita #page=N para abrir na página."""
    if sys.platform.startswith("win"):
        for c in _NAVEGADORES_WINDOWS:
            caminho = os.path.expandvars(c)
            if Path(caminho).is_file():
                return caminho
        return None
    for nome in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
        achado = shutil.which(nome)
        if achado:
            return achado
    return None


def caminho_seguro(pasta_originais: Path, relativo_ao_caso: str, raiz_caso: Path) -> Path:
    """Resolve o caminho e recusa o que estiver fora da pasta de originais."""
    alvo = (raiz_caso / relativo_ao_caso).resolve()
    if not alvo.is_relative_to(pasta_originais.resolve()):
        raise PermissionError(f"Fora da pasta de originais: {relativo_ao_caso}")
    if not alvo.is_file():
        raise FileNotFoundError(f"Original não encontrado: {relativo_ao_caso}")
    return alvo


def comando_para_abrir(arquivo: Path, pagina: int | None = None) -> list[str] | None:
    """O comando que abre o arquivo na página; None quando o jeito é o programa padrão do sistema."""
    if arquivo.suffix.lower() == ".pdf" and pagina:
        nav = navegador_com_pdf()
        if nav:
            return [nav, f"{arquivo.as_uri()}#page={pagina}"]
    if sys.platform.startswith("win"):
        return None  # os.startfile: o programa padrão do Windows para a extensão
    return ["open" if sys.platform == "darwin" else "xdg-open", str(arquivo)]


def abrir(arquivo: Path, pagina: int | None = None) -> str:
    """Abre o arquivo. Retorna como abriu, para a mensagem da interface."""
    cmd = comando_para_abrir(arquivo, pagina)
    if cmd is None:
        os.startfile(arquivo)  # type: ignore[attr-defined]
        return "no programa padrão" + (f" (vá à p. {pagina})" if pagina else "")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"na p. {pagina}" if "#page=" in cmd[-1] else "no programa padrão"
