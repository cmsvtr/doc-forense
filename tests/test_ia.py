"""IA local contra um servidor que responde como o Ollama (o Ollama real não roda no CI)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import forense.ia as ia


class _FalsoOllama(BaseHTTPRequestHandler):
    pedidos: list = []

    def log_message(self, *a):
        pass

    def _responder(self, dados):
        corpo = json.dumps(dados).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if self.path == "/api/version":
            self._responder({"version": "0.12.0"})
        elif self.path == "/api/tags":
            self._responder({"models": [{"name": "qwen2.5:7b"}, {"name": "gpt-oss:120b-cloud"}]})

    def do_POST(self):
        pedido = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FalsoOllama.pedidos.append(pedido)
        self._responder({
            "response": json.dumps({"empresas": ["Alfa", "Beta"], "conduta": "divisão de lotes"}),
            "prompt_eval_count": 2500, "prompt_eval_duration": 50e9,   # 50 tokens/s
            "eval_count": 100, "eval_duration": 20e9,                   # 5 tokens/s
            "load_duration": 3e9, "total_duration": 73e9,
        })


@pytest.fixture
def ollama(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _FalsoOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(ia, "ENDERECO", f"http://127.0.0.1:{srv.server_port}")
    _FalsoOllama.pedidos.clear()
    yield srv
    srv.shutdown()


def test_situacao(ollama):
    s = ia.situacao("qwen2.5:7b")
    assert s["ativo"] and s["versao"] == "0.12.0" and s["modelo_baixado"]
    assert not ia.situacao("llama3")["modelo_baixado"]


def test_ollama_desligado(monkeypatch):
    monkeypatch.setattr(ia, "ENDERECO", "http://127.0.0.1:9")
    s = ia.situacao()
    assert not s["ativo"] and "não respondeu" in s["erro"]


def test_medir_velocidade(ollama):
    v = ia.medir_velocidade("qwen2.5:7b")
    assert v["leitura_tokens_s"] == 50.0 and v["escrita_tokens_s"] == 5.0
    assert v["estimativa_s_por_trecho"] == 2500 // 50 + 400 // 5   # 50 s lendo + 80 s escrevendo
    assert v["json_valido"] and v["resposta"]["empresas"] == ["Alfa", "Beta"]
    p = _FalsoOllama.pedidos[-1]
    # contexto explícito (o padrão do Ollama corta texto longo) e resultado reprodutível
    assert p["options"]["num_ctx"] == ia.CONTEXTO and p["options"]["temperature"] == 0 and p["format"] == "json"


def test_imprimir_avisa_modelo_na_nuvem(ollama, capsys):
    assert ia.imprimir("qwen2.5:7b", medir=False)
    assert "NUVEM" in capsys.readouterr().out
