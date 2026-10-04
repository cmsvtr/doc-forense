"""Importação de uma pasta de autos do computador para o caso, direto do disco.

Substitui o envio pelo navegador, que carregava tudo na memória (MemoryError em pastas grandes) e,
enviando arquivo por arquivo, perdia as subpastas que dão o número SEI aos anexos. Aqui a pasta é
copiada com a estrutura inteira para originais/<nome da pasta>/, em segundo plano. Os arquivos de
origem não são alterados (só lidos).
"""

import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .caso import Caso


def escolher_pasta() -> str | None:
    """Abre o seletor de pastas do sistema e devolve o caminho escolhido (None se cancelado ou
    indisponível). Roda em processo separado: a janela não trava a interface."""
    if sys.platform.startswith("win"):
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$dono = New-Object System.Windows.Forms.Form -Property @{TopMost=$true};"
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
            "$d.Description = 'Escolha a pasta dos autos a importar';"
            "if ($d.ShowDialog($dono) -eq 'OK') { [Console]::OutputEncoding=[Text.Encoding]::UTF8; $d.SelectedPath }"
        )
        cmd = ["powershell", "-NoProfile", "-STA", "-Command", script]
        opcoes = {"creationflags": 0x08000000}  # sem janela de console
    else:
        cmd = [sys.executable, "-c",
               "import tkinter as tk; from tkinter import filedialog; r = tk.Tk(); r.withdraw();"
               "print(filedialog.askdirectory(title='Escolha a pasta dos autos'))"]
        opcoes = {}
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=900, **opcoes)
    except (OSError, subprocess.SubprocessError):
        return None
    caminho = r.stdout.decode("utf-8", errors="replace").strip()
    return caminho or None


def validar_origem(caso: Caso, origem: Path) -> Path:
    origem = Path(origem).expanduser().resolve()
    if not origem.is_dir():
        raise FileNotFoundError(f"Pasta não encontrada: {origem}")
    raiz = caso.raiz.resolve()
    if origem == raiz or raiz.is_relative_to(origem) or origem.is_relative_to(raiz):
        raise ValueError("A pasta de origem não pode conter o caso nem estar dentro dele.")
    return origem


def importar_pasta(caso: Caso, origem: Path, log=print, progresso=None) -> dict:
    """Copia a pasta (com subpastas) para originais/<nome da pasta>/. Arquivo idêntico já presente é
    pulado; arquivo diferente com o mesmo nome ganha sufixo (nada é sobrescrito)."""
    origem = validar_origem(caso, origem)
    destino_base = caso.originais / origem.name
    arquivos = [Path(r) / n for r, _, ns in os.walk(origem) for n in sorted(ns)
                if not n.startswith(("~$", ".")) and n.lower() not in ("thumbs.db", "desktop.ini")]
    resumo = {"origem": str(origem), "destino": caso.relativo(destino_base) if destino_base.exists() else
              f"originais/{origem.name}", "copiados": 0, "ja_existentes": 0, "renomeados": 0, "erros": 0,
              "total": len(arquivos)}
    for k, arq in enumerate(arquivos, 1):
        destino = destino_base / arq.relative_to(origem)
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            if destino.exists():
                if filecmp.cmp(arq, destino, shallow=False):
                    resumo["ja_existentes"] += 1
                    continue
                base, ext, n = destino.stem, destino.suffix, 2
                while destino.exists():
                    destino = destino.with_name(f"{base} ({n}){ext}")
                    n += 1
                resumo["renomeados"] += 1
            shutil.copy2(arq, destino)
            resumo["copiados"] += 1
        except OSError as e:
            resumo["erros"] += 1
            log(f"  [!] {arq}: {e}")
        if progresso and (k % 20 == 0 or k == len(arquivos)):
            progresso(k, len(arquivos), arq.name)
    resumo["destino"] = f"originais/{origem.name}"
    caso.registrar("pasta_importada", **resumo)
    log(f"[✓] Importação: {resumo}")
    return resumo
