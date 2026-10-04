from forense.consolidacao import chave_nome, dramatis_personae, linha_do_tempo


def _a(id_, tipo, dados, status="validado", loc="SEI nº 1, p. 1"):
    return {"id": id_, "tipo": tipo, "dados": dados, "localizador": loc, "caminho": "originais/x.pdf",
            "pagina": 1, "trecho_fonte": "trecho", "revisao": {"status": status}}


ACHADOS = [
    _a("1", "pessoas", {"nome": "Carlos Mendes", "cargo": "Diretor"}),
    _a("2", "pessoas", {"nome": "CARLOS MENDES", "empresa": "Alfa"}, loc="SEI nº 2, p. 4"),
    _a("3", "pessoas", {"nome": "Carlos"}),                                   # não junta com «Carlos Mendes»
    _a("4", "pessoas", {"nome": "Marcos Souza"}, status="rejeitado"),
    _a("5", "pessoas", {"nome": "Ana Lima"}, status="pendente"),
    _a("6", "empresas", {"nome": "Engenharia Alfa S/A", "cnpj": "11.222.333/0001-81"}),
    _a("7", "empresas", {"nome": "Engenharia Alfa S.A."}, loc="SEI nº 3, p. 2"),  # sem CNPJ: junta pelo nome
    _a("8", "eventos", {"data": "", "categoria": "outro", "descricao_ia": "sem data"}),
    _a("9", "eventos", {"data": "2024-03-14", "categoria": "x", "descricao_ia": "b", "participantes": ["Carlos Mendes"]}),
    _a("10", "eventos", {"data": "2023-01-02", "categoria": "x", "descricao_ia": "a"}),
]


def test_dramatis_so_validados_e_junta_grafias():
    dp = dramatis_personae(ACHADOS)
    nomes = {p["nome"]: p for p in dp["pessoas"]}
    assert set(nomes) == {"Carlos Mendes", "Carlos"}                          # rejeitado e pendente fora
    cm = nomes["Carlos Mendes"]
    assert cm["grafias"] == ["CARLOS MENDES", "Carlos Mendes"] and cm["cargos"] == ["Diretor"]
    assert cm["empresas"] == ["Alfa"] and cm["documentos"] == ["SEI nº 1", "SEI nº 2"]
    assert len(dp["empresas"]) == 1 and len(dp["empresas"][0]["fontes"]) == 2
    assert "Ana Lima" in {p["nome"] for p in dramatis_personae(ACHADOS, incluir_pendentes=True)["pessoas"]}


def test_linha_do_tempo_ordenada_sem_data_no_fim():
    lt = linha_do_tempo(ACHADOS)
    assert [e["data"] for e in lt] == ["2023-01-02", "2024-03-14", ""]


def test_chave_nome():
    assert chave_nome("Engenharia Alfa S/A") == chave_nome("ENGENHARIA ALFA S.A.")
    assert chave_nome("José da Silva") == chave_nome("JOSE DA SILVA")
