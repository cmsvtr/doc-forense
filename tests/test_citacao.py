from forense.citacao import aparece, localizar

PAGS = [
    {"n": 1, "texto": "Ata de reunião.\nPresentes os diretores comerciais."},
    {"n": 2, "texto": "Ficou acertado manter os preços da tabela única e a divi-\nsão de clientes por região a partir de junho."},
    {"n": 3, "texto": "Proposta de cobertura com va1or acima do orçamento."},  # OCR: «va1or»
]


def test_literal_ignora_acento_maiuscula_pontuacao_e_hifen():
    r = localizar("MANTER OS PRECOS DA TABELA UNICA e a divisão de clientes", PAGS)
    assert r["pagina"] == 2 and r["literal"]
    assert r["trecho_fonte"].startswith("manter os preços da tabela única")  # devolve o texto da fonte
    assert "divi-\nsão de clientes" in r["trecho_fonte"]


def test_aproximada_tolera_erro_de_ocr():
    r = localizar("proposta de cobertura com valor acima do orçamento", PAGS)
    assert r["pagina"] == 3 and not r["literal"] and r["similaridade"] >= 0.9


def test_citacao_inventada_ou_curta_demais_e_recusada():
    assert localizar("as empresas combinaram dividir os lotes do pregão", PAGS) is None
    assert localizar("a empresa", PAGS) is None  # curta demais para provar algo
    assert localizar("", PAGS) is None


def test_parafrase_nao_passa():
    # a IA «melhorou» o texto: não é citação, é paráfrase
    assert localizar("decidiram conservar os valores da lista comum", PAGS) is None


def test_aparece():
    assert aparece("Diretores Comerciais", PAGS[0]["texto"])
    assert not aparece("Carlos Mendes", PAGS[0]["texto"])
