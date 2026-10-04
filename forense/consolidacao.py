"""Dramatis personae e linha do tempo a partir dos achados VALIDADOS pelo analista.

Junta só o que é seguramente o mesmo: nomes iguais ignorando acentos, maiúsculas e pontuação
(«CARLOS MENDES» = «Carlos Mendes»), e empresas pelo CNPJ quando houver. «Carlos» e «Carlos
Mendes» continuam separados: decidir que são a mesma pessoa é juízo do analista.
"""

import re
import unicodedata
from collections import OrderedDict


def chave_nome(nome: str) -> str:
    base = "".join(c for c in unicodedata.normalize("NFD", nome.lower()) if not unicodedata.combining(c))
    base = re.sub(r"\bs\s*[./]?\s*a\b\.?", " sa ", base)  # S/A, S.A., SA
    return " ".join(re.findall(r"[a-z0-9]+", base))


def _filtrar(achados: list[dict], incluir_pendentes: bool) -> list[dict]:
    aceitos = {"validado", "pendente"} if incluir_pendentes else {"validado"}
    return [a for a in achados if a.get("revisao", {}).get("status", "pendente") in aceitos]


def _fonte(a: dict) -> dict:
    return {"localizador": a["localizador"], "caminho": a["caminho"], "pagina": a["pagina"],
            "trecho": a["trecho_fonte"], "achado_id": a["id"], "documento_id": a.get("documento_id"),
            "correcoes": a.get("correcoes", {}), "status": a.get("revisao", {}).get("status", "pendente")}


def dramatis_personae(achados: list[dict], incluir_pendentes: bool = False) -> dict:
    pessoas: "OrderedDict[str, dict]" = OrderedDict()
    empresas: "OrderedDict[str, dict]" = OrderedDict()
    for a in _filtrar(achados, incluir_pendentes):
        d = a["dados"]
        if a["tipo"] == "pessoas":
            p = pessoas.setdefault(chave_nome(d["nome"]), {"nome": d["nome"], "grafias": set(), "cargos": set(),
                                                           "empresas": set(), "fontes": []})
            p["grafias"].add(d["nome"])
            if d.get("cargo"):
                p["cargos"].add(d["cargo"])
            if d.get("empresa"):
                p["empresas"].add(d["empresa"])
            p["fontes"].append(_fonte(a))
        elif a["tipo"] == "empresas":
            chave = re.sub(r"\D", "", d["cnpj"]) if d.get("cnpj") else chave_nome(d["nome"])
            e = empresas.setdefault(chave, {"nome": d["nome"], "grafias": set(), "cnpjs": set(), "fontes": []})
            e["grafias"].add(d["nome"])
            if d.get("cnpj"):
                e["cnpjs"].add(d["cnpj"])
            e["fontes"].append(_fonte(a))
    # empresa citada sem CNPJ e, noutro achado, com CNPJ: junta pelo nome
    por_nome = {chave_nome(n): k for k, e in empresas.items() if e["cnpjs"] for n in e["grafias"]}
    for k in [k for k, e in empresas.items() if not e["cnpjs"]]:
        destino = por_nome.get(chave_nome(empresas[k]["nome"]))
        if destino and destino != k:
            empresas[destino]["fontes"] += empresas[k]["fontes"]
            empresas[destino]["grafias"] |= empresas[k]["grafias"]
            del empresas[k]

    def finalizar(itens):
        saida = []
        for v in itens.values():
            v = {k: sorted(x) if isinstance(x, set) else x for k, x in v.items()}
            v["documentos"] = sorted({f["localizador"].rsplit(", p.", 1)[0] for f in v["fontes"]})
            saida.append(v)
        return sorted(saida, key=lambda x: (-len(x["documentos"]), x["nome"].lower()))

    return {"pessoas": finalizar(pessoas), "empresas": finalizar(empresas)}


def linha_do_tempo(achados: list[dict], incluir_pendentes: bool = False) -> list[dict]:
    eventos = []
    for a in _filtrar(achados, incluir_pendentes):
        if a["tipo"] != "eventos":
            continue
        d = a["dados"]
        eventos.append({"data": d.get("data") or "", "categoria": d.get("categoria", "outro"),
                        "descricao_ia": d.get("descricao_ia", ""), "participantes": d.get("participantes", []),
                        **_fonte(a)})
    return sorted(eventos, key=lambda e: (e["data"] == "", e["data"], e["localizador"]))
