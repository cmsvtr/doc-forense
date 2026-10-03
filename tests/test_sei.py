from forense.extrator_pdf import decidir_ocr
from forense.processamento import PARAMETROS_PADRAO
from forense.sei import identificar, localizador


def test_sei_pelo_nome_do_arquivo():
    s = identificar("SEI_08700/[588]-1215707_E_mail.pdf", ".pdf", "")
    assert s["numero"] == "1215707" and s["ordem_arvore"] == 588
    assert s["tipo_no_nome"] == "E mail"
    assert s["tipo_no_nome_confiavel"] is False  # PDF: o tipo é o que quem protocolou escolheu


def test_sei_html_com_numero_do_ato():
    texto = "SEI/CADE - 0576611 - Nota Técnica Confidencial\nNOTA TÉCNICA Nº 15/2019/CGAA8/SGA2/SG/CADE"
    s = identificar("[363]-0576611_Nota_Tecnica_Confidencial_15_2019.html", ".html", texto)
    assert s["numero"] == "0576611"
    assert s["tipo_no_nome"] == "Nota Tecnica Confidencial"
    assert s["tipo_no_nome_confiavel"] is True
    assert s["numero_ato"] == "15/2019"


def test_sei_da_pasta_de_anexo_e_do_cabecalho():
    s = identificar("[104]-1157123_Anexo/Ata abertura lote 1.pdf", ".pdf", "")
    assert s["numero"] == "1157123" and s["fonte"] == "pasta de anexo"
    assert s["anexo"] == "Ata abertura lote 1.pdf"
    s = identificar("documento.pdf", ".pdf", "SEI/CADE - 1197874 - Nota Técnica")
    assert s["numero"] == "1197874" and s["fonte"] == "cabeçalho"
    assert identificar("contrato_alfa.pdf", ".pdf", "sem número") is None


def test_localizador():
    doc = {"arquivo": {"nome": "x.pdf"}, "sei": {"numero": "1215707"}}
    assert localizador(doc, [3]) == "SEI nº 1215707, p. 3"
    assert localizador(doc, [3, 4]) == "SEI nº 1215707, pp. 3, 4"
    assert localizador({"arquivo": {"nome": "x.pdf"}, "sei": None}) == "x.pdf"


def test_decisao_de_ocr():
    p = PARAMETROS_PADRAO
    assert decidir_ocr("x" * 150, 0.0, p).startswith("pouco texto")
    assert decidir_ocr("x" * 300, 0.0, p) is None
    # carimbo do SEI sobre página escaneada: tem texto, mas a imagem cobre a página
    assert decidir_ocr("x" * 300, 0.95, p).startswith("imagem cobre")
    # página digital longa com imagem de fundo: o texto digital basta
    assert decidir_ocr("x" * 3000, 0.95, p) is None
