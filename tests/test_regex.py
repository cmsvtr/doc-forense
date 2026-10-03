from forense.regex_br import (
    cnpj_valido, cpf_valido, extrair_cnpjs, extrair_cpfs, extrair_datas, extrair_valores,
)
from forense.texto import normalizar


def test_cnpj_numerico_e_alfanumerico():
    assert cnpj_valido("11.222.333/0001-81")
    assert not cnpj_valido("11.222.333/0001-82")
    # exemplo oficial da Receita Federal para o CNPJ alfanumérico
    assert cnpj_valido("12.ABC.345/01DE-35")
    assert not cnpj_valido("12.ABC.345/01DE-34")
    assert not cnpj_valido("00.000.000/0000-00")


def test_extrair_cnpjs_formatado_e_sem_pontuacao():
    texto = "CNPJ 11.222.333/0001-81, também 11222333000181, inválido 11.222.333/0001-80, chave 1122233300018112345"
    assert extrair_cnpjs(texto) == ["11.222.333/0001-81", "11.222.333/0001-81"]


def test_cpf():
    assert cpf_valido("529.982.247-25")
    assert not cpf_valido("111.111.111-11")
    # telefone com 11 dígitos não pode virar CPF: só aceitamos CPF formatado
    assert extrair_cpfs("Tel 11987654321, CPF 529.982.247-25") == ["529.982.247-25"]


def test_datas():
    texto = ("Em 14/03/2024 e 1º de abril de 2024; versão 1.2.24; processo 0001234-56.2024.8.26.0100; "
             "em março de 2023; 31/02/2024 é inválida; 05.06.2024; 15/04/24.")
    datas = [(d["data"], d["precisao"]) for d in extrair_datas(texto)]
    assert datas == [
        ("2024-03-14", "dia"), ("2024-04-01", "dia"), ("2023-03", "mes"),
        ("2024-06-05", "dia"), ("2024-04-15", "dia"),
    ]


def test_valores():
    v = extrair_valores("R$ 1.250.000,00 e R$3,5 milhões e R$ 800 mil")
    assert [x["valor"] for x in v] == [1250000.0, 3500000.0, 800000.0]


def test_normalizar_preserva_comprimento():
    s = "Licitação, PREGÃO e ação"
    n = normalizar(s)
    assert n == "licitacao, pregao e acao"
    assert len(n) == len(s)
