"""«Pergunte aos autos»: resposta curta da IA local, montada só com as passagens encontradas.

A busca vem primeiro e é o que vale: o analista vê as passagens. A resposta da IA é opcional e
passa pela mesma conferência da extração: cada afirmação traz o trecho em que se apoia, e trecho
que não está nas passagens derruba a afirmação. Sem afirmação confirmada, o app diz que os
documentos encontrados não respondem com segurança, em vez de deixar o modelo improvisar.
"""

import json

from . import ia
from .caso import Caso, agora
from .citacao import localizar

PASSAGENS_NA_RESPOSTA = 8

ESQUEMA = {
    "type": "object",
    "properties": {
        "afirmacoes": {"type": "array", "items": {"type": "object", "properties": {
            "trecho": {"type": "string"}, "fonte": {"type": "integer"}, "afirmacao": {"type": "string"}},
            "required": ["trecho", "fonte", "afirmacao"]}},
        "os_trechos_respondem": {"type": "boolean"},
    },
    "required": ["afirmacoes", "os_trechos_respondem"],
}

INSTRUCOES = """Você responde perguntas sobre documentos de uma investigação de cartel usando SOMENTE as
passagens fornecidas dentro de <fonte n="...">.
Regras:
1. Cada afirmação precisa de apoio: primeiro copie em "trecho" as palavras exatas da passagem (5 a 40 palavras),
   indique em "fonte" o número dela e só então escreva a afirmação.
2. Não use conhecimento externo, não deduza além do texto, não opine sobre culpa ou ilicitude.
3. Se as passagens não respondem à pergunta, devolva "afirmacoes" vazia e "os_trechos_respondem": false.
4. No máximo 5 afirmações, curtas."""


def responder(caso: Caso, pergunta: str, resultados: list[dict], modelo: str = ia.MODELO_PADRAO) -> dict:
    fontes = resultados[:PASSAGENS_NA_RESPOSTA]
    blocos = "\n".join(f'<fonte n="{i}" citacao="{r["localizador"]}">\n{r["passagem"]}\n</fonte>'
                       for i, r in enumerate(fontes, 1))
    r = ia._pedir("/api/chat", {
        "model": modelo, "stream": False, "format": ESQUEMA,
        "messages": [{"role": "system", "content": INSTRUCOES},
                     {"role": "user", "content": f"{blocos}\n\n<pergunta>{pergunta}</pergunta>"}],
        "options": {"temperature": 0, "seed": 1, "num_ctx": ia.CONTEXTO, "num_predict": 1200},
        "keep_alive": "30m",
    }, tempo=1800)
    try:
        bruta = json.loads((r.get("message") or {}).get("content") or "{}")
    except ValueError:
        bruta = {}

    confirmadas, descartadas = [], []
    for a in bruta.get("afirmacoes") or []:
        if not isinstance(a, dict):
            continue
        n = a.get("fonte")
        # o trecho tem de estar na passagem indicada; se o número vier errado, procura nas outras
        ordem = ([fontes[n - 1]] if isinstance(n, int) and 1 <= n <= len(fontes) else []) + fontes
        achado = None
        for f in ordem:
            achado = localizar(a.get("trecho", ""), [{"n": f["pagina"], "texto": f["passagem"]}])
            if achado:
                confirmadas.append({"afirmacao_ia": (a.get("afirmacao") or "").strip(),
                                    "trecho_fonte": achado["trecho_fonte"], "literal": achado["literal"],
                                    "localizador": f["localizador"], "caminho": f["caminho"], "pagina": f["pagina"]})
                break
        if not achado:
            descartadas.append(a)

    resultado = {
        "pergunta": pergunta, "quando": agora(), "modelo": modelo,
        "afirmacoes": confirmadas, "descartadas": len(descartadas),
        "responde": bool(confirmadas) and bool(bruta.get("os_trechos_respondem", True)),
        "fontes": [f["localizador"] for f in fontes],
    }
    caso.analise.mkdir(parents=True, exist_ok=True)
    with open(caso.analise / "perguntas.jsonl", "a", encoding="utf-8") as arq:
        arq.write(json.dumps(resultado, ensure_ascii=False) + "\n")
    caso.registrar("pergunta_respondida", afirmacoes=len(confirmadas), descartadas=len(descartadas))
    return resultado
