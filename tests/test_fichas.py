"""Fichas individuais e correções do analista (conferidas pela máquina, aplicadas como sobreposição)."""

import json

from forense.analise_ia import achados_do_caso, analisar_caso, marcar
from forense.comunicacoes import construir_teia
from forense.correcoes import ler, registrar
from forense.fichas import fichas, gerar_word
from forense.processamento import processar_caso

from .test_analise_ia import ollama  # noqa: F401  (fixture)


def _preparar(caso):
    processar_caso(caso, workers=2, log=lambda m: None)
    analisar_caso(caso, "qwen2.5:7b", log=lambda m: None)
    for a in achados_do_caso(caso):
        marcar(caso, a["id"], "validado")


def test_ficha_junta_achados_e_teia(caso, ollama):
    _preparar(caso)
    [f] = fichas(caso, ["Carlos Mendes"])
    assert f["enderecos"] == ["carlos.mendes@alfaengenharia.com.br"]
    assert f["organizacoes"] == ["alfaengenharia.com.br"]
    assert f["contrapartes"][0]["pessoa"] == "Marcos Souza" and f["contrapartes"][0]["entre_organizacoes"]
    origens = {i["origem"] for i in f["linha_do_tempo"]}
    assert origens == {"achado", "mensagem"}                     # evento validado + mensagens da teia
    assert all(i["localizador"] and i["caminho"] and i["alvo"]["id"] for i in f["linha_do_tempo"])
    datas = [i["data"] for i in f["linha_do_tempo"] if i["data"]]
    assert datas == sorted(datas)
    destino = gerar_word(caso, f)
    assert destino.exists() and destino.name.startswith("ficha_Carlos_Mendes")


def test_correcao_conferida_e_sobreposta(caso, ollama):
    _preparar(caso)
    evento = next(a for a in achados_do_caso(caso) if a["tipo"] == "eventos" and a["dados"].get("data"))
    alvo = {"tipo": "achado", "id": evento["id"], "documento_id": evento["documento_id"], "pagina": evento["pagina"],
            "localizador": evento["localizador"], "trecho": evento["trecho_fonte"]}

    c1 = registrar(caso, alvo, "data", evento["dados"]["data"], "2024-03-13", "a mensagem citada é a do dia 13")
    assert c1["conferencia_maquina"] == "confere com o texto"            # 13/03/2024 está na página
    c2 = registrar(caso, alvo, "participantes", "Carlos Mendes", "Carlos Mendes; Fulano Inexistente", "faltou")
    assert c2["conferencia_maquina"] == "não encontrado no texto"        # a máquina não aceita às cegas

    corrigido = next(a for a in achados_do_caso(caso) if a["id"] == evento["id"])
    assert corrigido["dados"]["data"] == "2024-03-13"
    assert corrigido["dados_originais"]["data"] == evento["dados"]["data"]  # original guardado
    assert corrigido["correcoes"]["data"]["conferencia"] == "confere com o texto"

    linhas = ler(caso)
    assert len(linhas) == 2 and linhas[0]["alvo"]["trecho"] and linhas[0]["versoes"]["extrator"]
    assert json.loads((caso.analise / "correcoes.jsonl").read_text(encoding="utf-8").splitlines()[0])["motivo"]


def test_correcao_de_mensagem_muda_a_teia(caso, ollama):
    _preparar(caso)
    t = construir_teia(caso)
    m = next(m for p in t["pares"] for m in p["mensagens"] if m["meio"] == "e-mail")
    alvo = {"tipo": "mensagem", "id": m["id"], "documento_id": m["documento_id"], "pagina": m["pagina"],
            "localizador": m["localizador"], "trecho": ""}
    registrar(caso, alvo, "assunto", m["assunto"], "Pregão 12/2024 (lote 2)", "assunto completo")
    t2 = construir_teia(caso)
    m2 = next(x for p in t2["pares"] for x in p["mensagens"] if x["id"] == m["id"])
    assert m2["assunto"] == "Pregão 12/2024 (lote 2)" and m2["correcoes"]["assunto"]["conferencia"] == "não verificável"


def test_conferencia_de_remetente_e_destinatarios():
    from forense.correcoes import conferir

    texto = "De: Carlos Mendes <carlos@alfa.com.br>\nPara: Marcos Souza; Paula"
    assert conferir("para", "Marcos Souza; Paula", texto) == "confere com o texto"
    assert conferir("de", "Fulano <carlos@alfa.com.br>", texto) == "confere com o texto"   # o endereço basta
    assert conferir("para", "Marcos Souza; Beltrano", texto) == "não encontrado no texto"
    assert conferir("assunto", "qualquer", texto) == "não verificável"
