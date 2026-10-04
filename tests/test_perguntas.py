"""«Pergunte aos autos»: busca híbrida e resposta com citação conferida."""

import json

from forense.perguntas import responder
from forense.processamento import processar_caso
from forense.vetores import buscar_hibrida, consulta_por_palavras, indexar, passagens, situacao

from .test_analise_ia import ollama  # noqa: F401  (fixture)


def test_passagens_nao_atravessam_paginas():
    doc = {"paginas": [{"n": 1, "texto": " ".join(f"a{i}" for i in range(600))}, {"n": 2, "texto": "fim da ata"}]}
    ps = passagens(doc)
    assert [p["pagina"] for p in ps] == [1, 1, 1, 2]
    assert ps[0]["texto"].split()[-40:] == ps[1]["texto"].split()[:40]          # sobreposição
    assert ps[-1]["texto"] == "fim da ata"


def test_consulta_por_palavras():
    assert consulta_por_palavras("Quais empresas combinaram propostas no pregão?") == "empresas OU combinaram OU propostas OU pregão"


def test_indexar_incremental_e_busca_hibrida(caso, ollama):
    processar_caso(caso, workers=2, log=lambda m: None)
    r = indexar(caso, log=lambda m: None)
    assert r["documentos_refeitos"] == r["total"] and r["passagens"] > 0
    assert indexar(caso, log=lambda m: None)["documentos_refeitos"] == 0       # nada refeito
    s = situacao(caso)
    assert s["documentos"] == s["total"]

    res = buscar_hibrida(caso, "quem ficou com o lote 1 do pregão?")
    assert res[0]["localizador"].startswith("pregao_12_2024.html")
    assert set(res[0]["origens"]) == {"palavra", "significado"}
    assert "lote 1" in res[0]["passagem"]


def test_sem_ollama_fica_a_busca_por_palavra(caso, ollama):
    processar_caso(caso, workers=2, log=lambda m: None)
    indexar(caso, log=lambda m: None)
    ollama.falhar = True
    res = buscar_hibrida(caso, "proposta de cobertura")
    assert res and all(r["origens"] == ["palavra"] for r in res)


def test_resposta_so_com_citacao_conferida(caso, ollama):
    processar_caso(caso, workers=2, log=lambda m: None)
    indexar(caso, log=lambda m: None)
    res = buscar_hibrida(caso, "quem ficou com o lote 1 do pregão?")
    ollama.resposta_pergunta = {"os_trechos_respondem": True, "afirmacoes": [
        {"fonte": 1, "trecho": "vocês entram com proposta de cobertura no lote 2 e nós ficamos com o lote 1",
         "afirmacao": "A empresa do remetente ficaria com o lote 1."},
        {"fonte": 1, "trecho": "a Alfa venceu todos os lotes do estado em 2023",            # inventado
         "afirmacao": "A Alfa venceu todos os lotes."},
    ]}
    r = responder(caso, "quem ficou com o lote 1 do pregão?", res)
    assert r["responde"] and len(r["afirmacoes"]) == 1 and r["descartadas"] == 1
    a = r["afirmacoes"][0]
    assert a["localizador"].startswith("pregao_12_2024.html") and "lote 1" in a["trecho_fonte"]
    linhas = (caso.analise / "perguntas.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(linhas[-1])["pergunta"] == "quem ficou com o lote 1 do pregão?"

    ollama.resposta_pergunta = {"os_trechos_respondem": True, "afirmacoes": [
        {"fonte": 2, "trecho": "o diretor confessou o cartel na reunião de dezembro", "afirmacao": "Houve confissão."}]}
    r = responder(caso, "houve confissão?", res)
    assert not r["responde"] and r["afirmacoes"] == []                            # nada confirmado: não responde
