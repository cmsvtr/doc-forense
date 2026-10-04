import sys
from pathlib import Path

import pytest

import forense.abrir as ab


def test_recusa_arquivo_fora_dos_originais(caso):
    with pytest.raises(PermissionError):
        ab.caminho_seguro(caso.originais, "../../../etc/passwd", caso.raiz)
    with pytest.raises(PermissionError):
        ab.caminho_seguro(caso.originais, "manifesto.json", caso.raiz)
    with pytest.raises(FileNotFoundError):
        ab.caminho_seguro(caso.originais, "originais/nao_existe.pdf", caso.raiz)
    assert ab.caminho_seguro(caso.originais, "originais/ata_reuniao.pdf", caso.raiz).name == "ata_reuniao.pdf"


def test_pdf_abre_na_pagina_pelo_navegador(monkeypatch, tmp_path):
    monkeypatch.setattr(ab, "navegador_com_pdf", lambda: r"C:\Edge\msedge.exe")
    arq = tmp_path / "[12]-1234567_E mail.pdf"
    cmd = ab.comando_para_abrir(arq, 7)
    assert cmd[0] == r"C:\Edge\msedge.exe"
    assert cmd[1].startswith("file:///") and cmd[1].endswith("#page=7")
    assert "%20" in cmd[1]  # espaço codificado na URL


def test_sem_navegador_ou_sem_pagina_usa_programa_padrao(monkeypatch, tmp_path):
    monkeypatch.setattr(ab, "navegador_com_pdf", lambda: None)
    monkeypatch.setattr(sys, "platform", "win32")
    assert ab.comando_para_abrir(tmp_path / "a.pdf", 3) is None      # os.startfile
    assert ab.comando_para_abrir(tmp_path / "a.html", None) is None
    monkeypatch.setattr(sys, "platform", "linux")
    assert ab.comando_para_abrir(tmp_path / "a.html", None) == ["xdg-open", str(tmp_path / "a.html")]
