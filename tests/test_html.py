from pathlib import Path

from forense.extrator_html import extrair_html, interpretar_data

from .conftest import EMAIL_HTML


def test_email_html(tmp_path: Path):
    p = tmp_path / "e.html"
    p.write_text(EMAIL_HTML, encoding="utf-8")
    r = extrair_html(p, {})
    texto = r["paginas"][0]["texto"]
    assert "proposta de cobertura" in texto
    assert "alert(" not in texto  # scripts são descartados
    assert r["html"]["titulo"] == "RE: Pregão 12/2024"

    msgs = r["emails"]
    assert len(msgs) == 2
    assert msgs[0]["de"].startswith("Carlos Mendes")
    assert msgs[0]["data_iso"] == "2024-03-14T10:32"
    assert msgs[0]["assunto"] == "RE: Pregão 12/2024"
    assert msgs[1]["data_iso"] == "2024-03-13T18:05"


def test_html_em_latin1(tmp_path: Path):
    p = tmp_path / "l.html"
    p.write_bytes('<html><head><meta charset="iso-8859-1"></head><body>Licitação ação</body></html>'.encode("latin-1"))
    assert "Licitação ação" in extrair_html(p, {})["paginas"][0]["texto"]


def test_interpretar_data():
    assert interpretar_data("Thu, 14 Mar 2024 10:32:00 -0300") == "2024-03-14T10:32"
    assert interpretar_data("segunda-feira, 4 de março de 2024 09h05") == "2024-03-04T09:05"
    assert interpretar_data("sem data") is None
