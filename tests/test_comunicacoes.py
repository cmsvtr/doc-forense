"""Teia de comunicações (sem IA) e tipos de comunicação na triagem."""

from forense.comunicacoes import construir_teia, grafo_dot, participantes
from forense.processamento import processar_caso
from forense.triagem import ler_triagem

CHAT = """14/03/2024 10:30 - Carlos Mendes: bom dia, e o lote 2?
14/03/2024 10:31 - Marcos Souza: vocês entram com cobertura
14/03/2024 10:35 - Carlos Mendes: combinado
[15/03/2024, 09:00:12] Paulo Lima: entro na próxima
"""

CARTA = """<html><body><p>Prezado Senhor Diretor,</p><p>Encaminhamos a tabela de preços para a próxima concorrência.</p>
<p>Atenciosamente,</p><p>Ana Paula Rocha</p></body></html>"""
ATA = """<html><body><h1>ATA DA REUNIÃO DO COMITÊ</h1><p>Presentes: diretores comerciais.</p></body></html>"""


def test_participantes():
    assert participantes("Carlos Mendes <Carlos@Alfa.com.br>; Marcos") == [("Carlos Mendes", "carlos@alfa.com.br"), ("Marcos", None)]
    assert participantes('"Souza, Marcos" <marcos@beta.com.br>') == [("Marcos Souza", "marcos@beta.com.br")]


def test_teia_emails_e_conversa(caso):
    (caso.originais / "conversa.txt").write_text(CHAT, encoding="utf-8")
    processar_caso(caso, workers=2, log=lambda m: None)
    t = construir_teia(caso)

    # e-mail: Carlos (alfaengenharia) <-> Marcos (betaconstrucoes), 2 mensagens, entre organizações
    par = next(p for p in t["pares"] if {p["rotulo_a"], p["rotulo_b"]} == {"Carlos Mendes", "Marcos Souza"})
    assert par["entre_organizacoes"] and par["total"] >= 2
    # a conversa sem e-mail casa com o endereço já visto para o mesmo nome
    ids = {p["a"] for p in t["pares"]} | {p["b"] for p in t["pares"]}
    assert "carlos.mendes@alfaengenharia.com.br" in ids and "nome:carlos mendes" not in ids
    assert any("conversa" in {m["meio"] for m in p["mensagens"]} for p in t["pares"])
    assert t["entre_organizacoes"][0]["organizacoes"] == ["alfaengenharia.com.br", "betaconstrucoes.com.br"]
    assert "--" in grafo_dot(t) and "#dc2626" in grafo_dot(t)          # linha vermelha entre organizações


def test_triagem_reconhece_outras_comunicacoes(caso):
    (caso.originais / "conversa.txt").write_text(CHAT, encoding="utf-8")
    (caso.originais / "carta.html").write_text(CARTA, encoding="utf-8")
    (caso.originais / "ata.html").write_text(ATA, encoding="utf-8")
    processar_caso(caso, workers=2, log=lambda m: None)
    t = {r["arquivo"]: r for r in ler_triagem(caso)["documentos"]}
    assert t["conversa.txt"]["tipo_comunicacao"] == "conversa"
    assert t["carta.html"]["tipo_comunicacao"] == "carta ou ofício"
    assert t["ata.html"]["tipo_comunicacao"] == "ata de reunião"
    assert t["pregao_12_2024.html"]["tipo_comunicacao"] == "e-mail"
    assert t["boletim.htm"]["tipo_comunicacao"] is None
    assert all(t[n]["prioritario"] for n in ("conversa.txt", "carta.html", "ata.html"))
