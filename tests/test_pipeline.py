"""Teste de ponta a ponta: processa o caso sintético e confere cada camada."""

import json

from docx import Document

from forense.indice import buscar, entidades_do_caso
from forense.processamento import ler_progresso, processar_caso
from forense.relatorio import gerar_relatorio
from forense.triagem import ler_triagem

from .conftest import ocr_disponivel


def _por_nome(caso):
    return {d["arquivo"]["nome"]: d for d in caso.documentos()}


def test_pipeline_completo(caso):
    resumo = processar_caso(caso, workers=2, log=lambda m: None)
    assert resumo["erros"] == 0

    docs = _por_nome(caso)
    # duplicata vira um único documento com dois caminhos; arquivo temporário do Office é ignorado
    boletim = docs.get("boletim.htm") or docs["copia_do_boletim.html"]
    assert len(boletim["arquivo"]["caminhos"]) == 2
    assert not any(n.startswith("~$") for n in docs)

    ata = docs["ata_reuniao.pdf"]
    assert ata["paginas"][0]["metodo"] == "texto_digital"
    assert "divisão de clientes" in ata["paginas"][0]["texto"]
    assert [c["valor"] for c in ata["entidades"]["cpfs"]] == ["529.982.247-25"]

    email = docs["pregao_12_2024.html"]
    assert {c["valor"] for c in email["entidades"]["cnpjs"]} == {"11.222.333/0001-81", "12.ABC.345/01DE-35"}
    assert len(email["emails"]) == 2

    manifesto = json.loads(caso.manifesto.read_text(encoding="utf-8"))
    assert manifesto["arquivos_ignorados"] == ["originais/planilha.xlsx"]
    assert caso.verificar_integridade()["ok"]
    assert ler_progresso(caso)["estado"] == "concluido"

    # busca sem acento encontra texto com acento
    assert any(r["nome"] == "pregao_12_2024.html" for r in buscar(caso, "licitacao"))
    assert any(r["nome"] == "ata_reuniao.pdf" for r in buscar(caso, '"tabela unica"'))
    assert buscar(caso, 'termo"; DROP TABLE x; --') == []  # entrada maliciosa não quebra a busca
    assert any(e["valor"] == "11.222.333/0001-81" for e in entidades_do_caso(caso))

    # triagem: documentos colusivos à frente do boletim neutro
    ranking = [r["arquivo"] for r in ler_triagem(caso)["documentos"]]
    assert ranking[0] == "pregao_12_2024.html"
    assert ranking.index("ata_reuniao.pdf") < ranking.index(boletim["arquivo"]["nome"])

    # relatório Word
    destino = gerar_relatorio(caso)
    texto = "\n".join(p.text for p in Document(destino).paragraphs)
    assert "Por onde começar" in texto
    assert "pregao_12_2024.html" in texto

    eventos = [e["evento"] for e in caso.eventos()]
    for esperado in ("caso_criado", "processamento_iniciado", "manifesto_gerado", "processamento_concluido", "relatorio_gerado"):
        assert esperado in eventos


def test_reprocessamento_incremental_e_adulteracao(caso):
    processar_caso(caso, workers=2, log=lambda m: None)
    segundo = processar_caso(caso, workers=2, log=lambda m: None)
    assert segundo["processados"] == 0  # nada foi refeito

    # adulterar um original é detectado
    alvo = caso.originais / "boletim.htm"
    alvo.write_text(alvo.read_text(encoding="utf-8") + " ", encoding="utf-8")
    r = caso.verificar_integridade()
    assert not r["ok"]
    assert any("ALTERADO" in p and "boletim.htm" in p for p in r["problemas"])

    # adulterar uma extração também
    j = next(caso.extraido.glob("*.json"))
    j.write_text(j.read_text(encoding="utf-8").replace('"ok"', '"OK"', 1), encoding="utf-8")
    assert any("Extração ALTERADA" in p for p in caso.verificar_integridade()["problemas"])


def test_original_removido_vai_para_arquivo(caso):
    processar_caso(caso, workers=2, log=lambda m: None)
    (caso.originais / "ata_reuniao.pdf").unlink()
    processar_caso(caso, workers=2, log=lambda m: None)
    assert "ata_reuniao.pdf" not in _por_nome(caso)
    assert any((caso.extraido / "removidos").glob("*.json"))


@ocr_disponivel
def test_ocr_pdf_escaneado(caso):
    processar_caso(caso, workers=2, log=lambda m: None)
    termo = _por_nome(caso)["termo_escaneado.pdf"]
    pg = termo["paginas"][0]
    assert pg["metodo"] == "ocr"
    assert pg["confianca_media"] > 70
    texto = pg["texto"].lower()
    assert "proposta de cobertura" in texto
    assert "subcontratação" in texto  # acentuação correta exige o modelo 'por'
    assert [c["valor"] for c in termo["entidades"]["cnpjs"]] == ["11.222.333/0001-81"]
    assert any(d["data"] == "2024-06-20" for d in termo["entidades"]["datas"])
    assert termo["extracao"]["ferramentas"]["traineddata_sha256"]
    assert any(r["nome"] == "termo_escaneado.pdf" for r in buscar(caso, "certame"))


@ocr_disponivel
def test_escaneado_com_carimbo_do_sei_passa_por_ocr(caso):
    processar_caso(caso, workers=2, log=lambda m: None)
    doc = _por_nome(caso)["[12]-1234567_E_mail.pdf"]
    pg = doc["paginas"][0]
    assert pg["metodo"] == "ocr" and pg["motivo_ocr"].startswith("imagem cobre")
    assert "rodízio" in pg["texto"]  # o conteúdo escaneado ficou visível
    assert "assinado eletronicamente" in pg["texto_digital_residual"]
    assert doc["sei"]["numero"] == "1234567"
    assert (caso.extraido / "caixas" / doc["documento_id"] / "p0001.tsv").exists()
    assert any(r["localizador"] == "SEI nº 1234567" for r in buscar(caso, "rodizio"))

    anexo = _por_nome(caso)["Ata abertura lote 1.html"]
    assert anexo["sei"]["fonte"] == "pasta de anexo" and anexo["sei"]["numero"] == "7654321"


@ocr_disponivel
def test_exportacao_sgnt(caso):
    from forense.exportar_sgnt import exportar

    processar_caso(caso, workers=2, log=lambda m: None)
    r = exportar(caso)
    corpus = caso.raiz / "exportacao_sgnt" / "corpus"
    tsv = corpus / "_caixas" / "[12]-1234567_E_mail" / "p0001.tsv"
    assert tsv.read_text(encoding="utf-8").startswith("level\tpage_num\tblock_num")
    assert "rodízio" in (corpus / "_caixas" / "[12]-1234567_E_mail" / "p0001.txt").read_text(encoding="utf-8")
    assert "rodízio" in (corpus / "1234567.txt").read_text(encoding="utf-8")
    assert (corpus / "7654321" / "Ata abertura lote 1.txt").exists()  # anexo herda o SEI da pasta
    cob = (corpus / "_cobertura.tsv").read_text(encoding="utf-8").splitlines()
    assert cob[0].startswith("arquivo\tids\tpaginas")
    assert r["paginas_com_caixas"] >= 2


def test_busca_desfaz_hifenizacao(caso):
    (caso.originais / "hifen.html").write_text(
        "<html><body><p>era preciso circulari-<br>zar a tabela</p></body></html>", encoding="utf-8")
    processar_caso(caso, workers=2, log=lambda m: None)
    assert any(r["nome"] == "hifen.html" for r in buscar(caso, "circularizar"))


def test_indice_antigo_e_reconstruido(caso):
    import sqlite3
    from contextlib import closing

    processar_caso(caso, workers=2, log=lambda m: None)
    with closing(sqlite3.connect(caso.indice)) as con:  # simula índice de versão anterior
        con.execute("PRAGMA user_version = 1")
        con.execute("ALTER TABLE documentos DROP COLUMN localizador")
        con.commit()
    assert any(r["nome"] == "pregao_12_2024.html" for r in buscar(caso, "cobertura"))


def test_windows_troca_recusada_enquanto_arquivo_aberto(caso, monkeypatch):
    """No Windows, os.replace falha («Acesso negado») se outro processo estiver lendo o destino."""
    import os

    import forense.caso as modulo_caso
    from forense.caso import escrever_json_atomico
    from forense.processamento import Progresso

    original = os.replace
    recusas = {"n": 0}

    def replace_como_windows(a, b):
        if recusas["n"] < 3:
            recusas["n"] += 1
            raise PermissionError(5, "Acesso negado")
        return original(a, b)

    monkeypatch.setattr(modulo_caso.os, "replace", replace_como_windows)
    destino = caso.raiz / "teste.json"
    escrever_json_atomico(destino, {"ok": 1})  # recusado 3 vezes, gravado na 4ª
    assert destino.exists() and recusas["n"] == 3
    assert not list(caso.raiz.glob(".tmp_*"))

    # recusa permanente: o progresso não derruba quem o grava
    monkeypatch.setattr(modulo_caso.os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError(5, "Acesso negado")))
    monkeypatch.setattr(modulo_caso.time, "sleep", lambda s: None)
    Progresso(caso).salvar()
    assert not list(caso.raiz.glob(".tmp_*"))


def test_sei_recalculado_sem_refazer_extracao(caso):
    """Mudança na regra do SEI não obriga a refazer o OCR: o número é recalculado no lugar."""
    import json

    processar_caso(caso, workers=2, log=lambda m: None)
    alvo = next(j for j in caso.extraido.glob("*.json")
                if json.loads(j.read_text(encoding="utf-8"))["arquivo"]["nome"] == "ata_reuniao.pdf")
    d = json.loads(alvo.read_text(encoding="utf-8"))
    d["sei"] = {"numero": "007351", "fonte": "pasta de anexo"}  # como a regra antiga gravaria
    extraido_em = d["extracao"]["extraido_em"]
    alvo.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    r = processar_caso(caso, workers=2, log=lambda m: None)
    assert r["processados"] == 0  # nada reextraído
    d = json.loads(alvo.read_text(encoding="utf-8"))
    assert d["sei"] is None and d["extracao"]["extraido_em"] == extraido_em
    assert any(e["evento"] == "metadados_atualizados" for e in caso.eventos())
    assert caso.verificar_integridade()["ok"]  # o manifesto foi refeito com o novo hash


def test_relatorio_tem_links_para_os_originais(caso):
    import zipfile
    from urllib.parse import unquote

    processar_caso(caso, workers=2, log=lambda m: None)
    destino = gerar_relatorio(caso)
    rels = zipfile.ZipFile(destino).read("word/_rels/document.xml.rels").decode("utf-8")
    alvos = {unquote(a) for a in __import__("re").findall(r'Target="([^"]+)" TargetMode="External"', rels)}
    assert alvos, "o relatório não tem links"
    for alvo in alvos:
        assert alvo.startswith("../originais/")
        assert (destino.parent / alvo).resolve().is_file(), alvo  # cada link aponta para um arquivo real
    # o arquivo dentro de subpasta é linkado pelo caminho real
    assert "../originais/emails/pregao_12_2024.html" in alvos
    xml = zipfile.ZipFile(destino).read("word/document.xml").decode("utf-8")
    assert xml.count("<w:hyperlink") >= len(alvos)
