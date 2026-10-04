"""Conversa com a IA local (Ollama), que roda neste computador: nada sai da máquina.

Nesta etapa: saber se o Ollama está instalado e ativo, se o modelo está baixado, e medir a
velocidade real, que decide quanto do caso dá para analisar com IA em tempo razoável.
"""

import json
import os
import urllib.error
import urllib.request

ENDERECO = os.environ.get("FORENSE_OLLAMA", "http://127.0.0.1:11434")
MODELO_PADRAO = os.environ.get("FORENSE_MODELO", "qwen2.5:7b")
# Janela de contexto pedida ao Ollama. O padrão dele é pequeno e CORTA texto longo sem avisar.
CONTEXTO = 8192

# Um trecho do tamanho que a etapa 2 vai mandar por vez (~1.500 palavras), para a medida valer.
_TRECHO_TESTE = (
    "De: Diretor Comercial da Empresa Alfa. Para: Gerente da Empresa Beta. Assunto: Pregão 12/2024. "
    "Conforme combinado no almoço da associação, vocês apresentam proposta de cobertura no lote 2 e nós "
    "ficamos com o lote 1. Na próxima licitação é a vez de vocês. Mantemos a tabela única de preços e o "
    "desconto máximo acertado. Melhor não tratar disso por e-mail; me ligue pelo celular pessoal. "
) * 25


def _pedir(caminho: str, dados: dict | None = None, tempo: float = 10) -> dict:
    req = urllib.request.Request(
        ENDERECO + caminho,
        data=json.dumps(dados).encode("utf-8") if dados is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=tempo) as r:
        return json.loads(r.read().decode("utf-8"))


def situacao(modelo: str = MODELO_PADRAO) -> dict:
    """Ollama ativo? Versão? Modelo baixado? Nunca levanta exceção."""
    s = {"endereco": ENDERECO, "ativo": False, "versao": None, "modelo": modelo,
         "modelo_baixado": False, "modelos": [], "digest": None, "erro": None}
    try:
        s["versao"] = _pedir("/api/version").get("version")
        s["ativo"] = True
        modelos = _pedir("/api/tags").get("models", [])
        nomes = [m.get("name", "") for m in modelos]
        s["modelos"] = nomes
        alvo = modelo if ":" in modelo else modelo + ":latest"
        s["modelo_baixado"] = alvo in nomes
        # digest: a versão exata dos pesos do modelo, registrada para a análise ser reproduzível
        s["digest"] = next((m.get("digest") for m in modelos if m.get("name") == alvo), None)
    except (urllib.error.URLError, OSError, ValueError) as e:
        s["erro"] = f"Ollama não respondeu em {ENDERECO} ({e})"
    return s


def medir_velocidade(modelo: str = MODELO_PADRAO) -> dict:
    """Manda um trecho do tamanho real e mede leitura (tokens/s do prompt) e escrita (tokens/s da
    resposta). Na CPU, a leitura de trechos longos costuma pesar mais que a escrita."""
    pergunta = (
        "Leia o trecho e responda SOMENTE em JSON, com as chaves empresas (lista) e conduta "
        "(uma frase).\n\nTRECHO:\n" + _TRECHO_TESTE
    )
    r = _pedir("/api/generate", {
        "model": modelo, "prompt": pergunta, "stream": False, "format": "json",
        "options": {"temperature": 0, "seed": 1, "num_ctx": CONTEXTO, "num_predict": 200},
        "keep_alive": "10m",
    }, tempo=900)
    ns = 1e9
    leitura = r.get("prompt_eval_count", 0) / (r.get("prompt_eval_duration", 0) / ns or 1)
    escrita = r.get("eval_count", 0) / (r.get("eval_duration", 0) / ns or 1)
    total_s = r.get("total_duration", 0) / ns
    carga_s = r.get("load_duration", 0) / ns
    # Estimativa por trecho analisado na etapa 2: ~2.500 tokens lidos e ~400 escritos.
    por_trecho = (2500 / leitura if leitura else 0) + (400 / escrita if escrita else 0)
    try:
        resposta = json.loads(r.get("response", "{}"))
    except ValueError:
        resposta = None
    return {
        "modelo": modelo,
        "tokens_lidos": r.get("prompt_eval_count", 0), "leitura_tokens_s": round(leitura, 1),
        "tokens_escritos": r.get("eval_count", 0), "escrita_tokens_s": round(escrita, 1),
        "carga_modelo_s": round(carga_s, 1), "total_s": round(total_s, 1),
        "estimativa_s_por_trecho": round(por_trecho), "json_valido": resposta is not None,
        "resposta": resposta,
    }


def imprimir(modelo: str = MODELO_PADRAO, medir: bool = True) -> bool:
    s = situacao(modelo)
    if not s["ativo"]:
        print(f"  [FALHA] {s['erro']}")
        print("          Abra o Ollama (menu Iniciar > Ollama) ou rode o instalar_ia.bat.")
        return False
    print(f"  [OK] Ollama {s['versao']} ativo em {s['endereco']}")
    nuvem = [m for m in s["modelos"] if "cloud" in m.lower()]
    if nuvem:
        print(f"  [ATENÇÃO] Modelos que rodam na NUVEM, não aqui: {', '.join(nuvem)}. Não os use com documentos do caso.")
    if not s["modelo_baixado"]:
        print(f"  [FALHA] Modelo {modelo} não baixado. Rode: ollama pull {modelo}")
        return False
    print(f"  [OK] Modelo {modelo} baixado")
    if not medir:
        return True
    print("  Medindo a velocidade com um trecho de ~1.500 palavras (pode levar alguns minutos na primeira vez)...")
    v = medir_velocidade(modelo)
    print(f"  Leitura: {v['leitura_tokens_s']} tokens/s ({v['tokens_lidos']} tokens)")
    print(f"  Escrita: {v['escrita_tokens_s']} tokens/s ({v['tokens_escritos']} tokens)")
    print(f"  Carga do modelo: {v['carga_modelo_s']} s · total: {v['total_s']} s · JSON válido: {'sim' if v['json_valido'] else 'NÃO'}")
    print(f"  Estimativa por trecho analisado na etapa 2: ~{v['estimativa_s_por_trecho']} s")
    return v["json_valido"]
