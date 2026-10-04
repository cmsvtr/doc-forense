"""Etapa 2 contra um servidor que responde como o Ollama, com os erros típicos de um modelo pequeno."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import forense.ia as ia
from forense.analise_ia import achados_do_caso, analisar_caso, dividir_em_trechos, ler_revisao, marcar
from forense.processamento import processar_caso

RESPOSTA_EMAIL = {
    "pessoas": [
        {"nome": "Carlos Mendes", "cargo": "Diretor Comercial",  # cargo não está no texto
         "trecho": "conforme combinado no almoço, vocês entram com proposta de cobertura no lote 2"},
        {"nome": "João Inventado",  # pessoa que não existe no documento
         "trecho": "conforme combinado no almoço, vocês entram com proposta de cobertura no lote 2"},
    ],
    "empresas": [
        {"nome": "Engenharia Alfa S/A", "cnpj": "11.222.333/0001-81",
         "trecho": "Engenharia Alfa S/A — CNPJ 11.222.333/0001-81"},
        {"nome": "Beta Construções Ltda", "cnpj": "99.999.999/0001-99",  # CNPJ falso
         "trecho": "Beta Construções Ltda — CNPJ 12.ABC.345/01DE-35"},
    ],
    "eventos": [
        {"data": "2024-03-14", "categoria": "proposta de cobertura, supressão ou rodízio em licitação",
         "descricao": "Combinação de proposta de cobertura no lote 2",
         "participantes": ["Carlos Mendes", "Fulano de Tal"],  # Fulano não está no texto
         "trecho": "vocês entram com proposta de cobertura no lote 2 e nós ficamos com o lote 1"},
        {"data": "2025-01-01", "categoria": "troca de informação sensível",  # data inventada
         "descricao": "Pergunta sobre preço do concorrente",
         "trecho": "qual vai ser o seu preço no lote 1"},
        {"data": "", "categoria": "divisão de mercado, clientes ou lotes",
         "descricao": "Divisão nacional", "trecho": "as empresas dividiram o mercado nacional de cimento"},  # não existe
    ],
}


class _Ollama(BaseHTTPRequestHandler):
    chamadas = 0
    falhar = False

    def log_message(self, *a):
        pass

    def _json(self, dados, codigo=200):
        corpo = json.dumps(dados).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if self.path == "/api/version":
            self._json({"version": "0.12.0"})
        else:
            self._json({"models": [{"name": "qwen2.5:7b", "digest": "abc123"}]})

    def do_POST(self):
        pedido = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if _Ollama.falhar:
            return self._json({"error": "sem memória"}, 500)
        _Ollama.chamadas += 1
        assert pedido["format"]["required"] == ["pessoas", "empresas", "eventos"]  # esquema imposto
        assert pedido["options"]["temperature"] == 0 and pedido["options"]["num_ctx"] == ia.CONTEXTO
        texto = pedido["messages"][-1]["content"]
        resposta = RESPOSTA_EMAIL if "proposta de cobertura no lote 2" in texto else {"pessoas": [], "empresas": [], "eventos": []}
        self._json({"message": {"content": json.dumps(resposta, ensure_ascii=False)},
                    "prompt_eval_count": 900, "prompt_eval_duration": 9e9, "eval_count": 120, "eval_duration": 6e9})


@pytest.fixture
def ollama(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Ollama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(ia, "ENDERECO", f"http://127.0.0.1:{srv.server_port}")
    _Ollama.chamadas, _Ollama.falhar = 0, False
    yield _Ollama
    srv.shutdown()


def _achados(caso, tipo):
    return [a for a in achados_do_caso(caso) if a["tipo"] == tipo]


def test_verificacao_filtra_o_que_a_ia_inventou(caso, ollama):
    processar_caso(caso, workers=2, log=lambda m: None)
    analisar_caso(caso, "qwen2.5:7b", log=lambda m: None)

    pessoas = _achados(caso, "pessoas")
    assert [p["dados"]["nome"] for p in pessoas] == ["Carlos Mendes"]           # João Inventado saiu
    assert "cargo" not in pessoas[0]["dados"]                                     # cargo inventado saiu
    assert any("Diretor Comercial" in a for a in pessoas[0]["alertas"])

    empresas = {e["dados"]["nome"]: e for e in _achados(caso, "empresas")}
    assert empresas["Engenharia Alfa S/A"]["dados"]["cnpj"] == "11.222.333/0001-81"
    assert "cnpj" not in empresas["Beta Construções Ltda"]["dados"]               # CNPJ falso saiu

    eventos = _achados(caso, "eventos")
    assert len(eventos) == 2                                                      # o «mercado de cimento» saiu
    cobertura = next(e for e in eventos if "cobertura" in e["dados"]["categoria"])
    assert cobertura["dados"]["data"] == "2024-03-14"                             # «14 de março de 2024» no texto
    assert cobertura["dados"]["participantes"] == ["Carlos Mendes"]               # Fulano saiu
    preco = next(e for e in eventos if "informação" in e["dados"]["categoria"])
    assert "data" not in preco["dados"]                                           # 2025-01-01 inventada saiu

    for a in achados_do_caso(caso):
        assert a["pagina"] == 1 and a["localizador"].endswith("p. 1")             # página da máquina
        assert a["revisao"]["status"] == "pendente"
        assert a["trecho_fonte"]                                                  # o texto como está na fonte

    doc_email = pessoas[0]["documento_id"]
    resultado = json.loads((caso.analise / "ia" / f"{doc_email}.json").read_text(encoding="utf-8"))
    assert resultado["modelo_digest"] == "abc123" and resultado["prompt_hash"]
    descartes = [d["motivo"] for t in resultado["trechos"] for d in t["descartados"]]
    assert "nome não aparece no texto" in descartes and "trecho não encontrado no documento" in descartes


def test_retomavel_e_revisao_sobrevive_a_nova_analise(caso, ollama):
    processar_caso(caso, workers=2, log=lambda m: None)
    analisar_caso(caso, "qwen2.5:7b", log=lambda m: None)
    chamadas = ollama.chamadas
    alvo = _achados(caso, "pessoas")[0]["id"]
    marcar(caso, alvo, "validado", "conferido na imagem")

    analisar_caso(caso, "qwen2.5:7b", log=lambda m: None)
    assert ollama.chamadas == chamadas                                            # nada refeito
    assert ler_revisao(caso)[alvo]["status"] == "validado"
    assert next(a for a in achados_do_caso(caso) if a["id"] == alvo)["revisao"]["nota"] == "conferido na imagem"


def test_ollama_falhando_deixa_trecho_para_a_proxima_rodada(caso, ollama):
    processar_caso(caso, workers=2, log=lambda m: None)
    ollama.falhar = True
    r = analisar_caso(caso, "qwen2.5:7b", primeiros=1, log=lambda m: None)
    assert r["erros"] >= 1 and not achados_do_caso(caso)
    ollama.falhar = False
    r = analisar_caso(caso, "qwen2.5:7b", primeiros=1, log=lambda m: None)
    assert r["erros"] == 0 and achados_do_caso(caso)


def test_recusa_modelo_na_nuvem_e_ollama_ausente(caso, monkeypatch):
    processar_caso(caso, workers=2, log=lambda m: None)
    monkeypatch.setattr(ia, "situacao", lambda m: {"ativo": True, "modelo_baixado": True, "digest": None, "erro": None})
    with pytest.raises(RuntimeError, match="nuvem"):
        analisar_caso(caso, "gpt-oss:120b-cloud", log=lambda m: None)
    monkeypatch.setattr(ia, "situacao", lambda m: {"ativo": False, "modelo_baixado": False, "digest": None,
                                                    "erro": "Ollama não respondeu"})
    with pytest.raises(RuntimeError, match="não respondeu"):
        analisar_caso(caso, "qwen2.5:7b", log=lambda m: None)


def test_dividir_em_trechos_preserva_paginas():
    doc = {"documento_id": "d1", "paginas": [
        {"n": 1, "texto": "palavra " * 500}, {"n": 2, "texto": "outra " * 500},
        {"n": 3, "texto": ("bloco " * 300 + "\n\n") * 5},   # página maior que o limite
        {"n": 4, "texto": ""}]}
    trechos = dividir_em_trechos(doc, palavras_max=1200)
    assert [[p["n"] for p in t["paginas"]] for t in trechos][0] == [1, 2]
    assert all(len(" ".join(p["texto"] for p in t["paginas"]).split()) <= 1200 for t in trechos)
    assert {p["n"] for t in trechos for p in t["paginas"]} == {1, 2, 3}           # página vazia não entra
    assert "[p. 3]" in trechos[-1]["texto_marcado"]


def test_relatorio_traz_so_os_validados(caso, ollama):
    from docx import Document

    from forense.relatorio import gerar_relatorio

    processar_caso(caso, workers=2, log=lambda m: None)
    analisar_caso(caso, "qwen2.5:7b", log=lambda m: None)
    pessoa = _achados(caso, "pessoas")[0]
    evento = next(a for a in _achados(caso, "eventos") if a["dados"].get("data"))
    marcar(caso, pessoa["id"], "validado")
    marcar(caso, evento["id"], "validado")
    texto = "\n".join(p.text for p in Document(gerar_relatorio(caso)).paragraphs)
    assert "Dramatis personae (validado pelo analista)" in texto and "Carlos Mendes" in texto
    assert "Engenharia Alfa" not in texto.split("6. Dramatis")[1].split("7. Linha")[0]   # pendente: fora
