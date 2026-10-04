"""Teia de comunicações: quem se comunica com quem, quantas vezes, quando e onde está a prova.

Feita pela máquina, sem IA, a partir de fontes estruturadas:
- cabeçalhos de e-mail (De → Para e Cc), em HTML, PDF impresso ou texto;
- conversas exportadas do WhatsApp (.txt): a mensagem de B logo depois da de A conta como
  comunicação entre A e B.
A identidade da pessoa é o endereço de e-mail quando existe (mais confiável que o nome); o nome sem
endereço é casado com o endereço que já apareceu com o mesmo nome. A organização é o domínio do
e-mail: comunicação entre domínios corporativos diferentes é destacada (concorrentes conversando).
"""

import hashlib
import re
from collections import defaultdict

from .caso import Caso
from .nomes import chave, emails_do_documento
from .sei import localizador
from .termos_cartel import DOMINIOS_GENERICOS

_ENDERECO_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Android: «14/03/2024 10:32 - Carlos: oi»  ·  iOS: «[14/03/2024, 10:32:15] Carlos: oi»
_CHAT_RE = re.compile(
    r"^\[?(\d{1,2})/(\d{1,2})/(\d{2,4}),?\s+(\d{1,2}):(\d{2})(?::\d{2})?\]?\s*(?:-\s*)?([^:\n]{2,60}?):\s+(.*)$")


def participantes(campo: str) -> list[tuple[str, str | None]]:
    """«Carlos Mendes <carlos@alfa.com>; Marcos» -> [("Carlos Mendes", "carlos@alfa.com"), ("Marcos", None)]."""
    partes, atual, aspas, angulo = [], "", False, False
    for c in campo or "":  # separa por «;» e «,», mas não dentro de aspas nem de <endereço>
        if c == '"':
            aspas = not aspas
        elif c == "<":
            angulo = True
        elif c == ">":
            angulo = False
        if c in ";," and not aspas and not angulo:
            partes.append(atual)
            atual = ""
        else:
            atual += c
    partes.append(atual)
    saida = []
    for parte in partes:
        parte = parte.strip()
        if not parte:
            continue
        m = _ENDERECO_RE.search(parte)
        endereco = m.group(0).lower() if m else None
        nome = re.sub(r"<[^>]*>|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|[\"'()\[\]]", " ", parte)
        nome = " ".join(nome.split())
        if nome.count(",") == 1:  # «Souza, Marcos» (formato do Outlook) -> «Marcos Souza»
            sobrenome, prenome = (x.strip() for x in nome.split(","))
            nome = f"{prenome} {sobrenome}".strip()
        nome = nome or (endereco.split("@")[0] if endereco else "")
        if nome or endereco:
            saida.append((nome, endereco))
    return saida


def mensagens_de_chat(doc: dict) -> list[dict]:
    """Pares de falas consecutivas de pessoas diferentes numa conversa exportada."""
    falas = []
    for pg in doc["paginas"]:
        for linha in (pg.get("texto") or "").split("\n"):
            m = _CHAT_RE.match(linha.strip())
            if m:
                d, mes, a, h, mi, autor, _ = m.groups()
                ano = int(a) + (2000 if len(a) == 2 else 0)
                falas.append({"autor": autor.strip(), "data": f"{ano:04d}-{int(mes):02d}-{int(d):02d}T{int(h):02d}:{mi}",
                              "pagina": pg["n"]})
    saida = []
    for anterior, atual in zip(falas, falas[1:]):
        if chave(anterior["autor"]) != chave(atual["autor"]):
            saida.append({"de": (atual["autor"], None), "para": [(anterior["autor"], None)], "cc": [],
                          "data": atual["data"], "assunto": "", "meio": "conversa", "pagina": atual["pagina"]})
    return saida


def mensagens_de_email(doc: dict) -> list[dict]:
    saida = []
    for msg in emails_do_documento(doc):
        remetentes = participantes(msg.get("de", ""))
        if not remetentes:
            continue
        para, cc = participantes(msg.get("para", "")), participantes(msg.get("cc", ""))
        if para or cc:
            saida.append({"de": remetentes[0], "para": para, "cc": cc, "data": msg.get("data_iso") or "",
                          "assunto": msg.get("assunto", ""), "meio": "e-mail", "pagina": None})
    return saida


def organizacao(endereco: str | None) -> str | None:
    if not endereco:
        return None
    dominio = endereco.split("@", 1)[1]
    return None if dominio in DOMINIOS_GENERICOS else dominio


def _como_texto(pessoas: list[tuple[str, str | None]]) -> str:
    """O inverso de participantes(): «Carlos Mendes <carlos@alfa.com>; Marcos» (para mostrar e corrigir)."""
    return "; ".join(f"{n} <{e}>" if n and e else (n or e or "") for n, e in pessoas)


def construir_teia(caso: Caso) -> dict:
    """{"pessoas": {id: {...}}, "pares": [...], "entre_organizacoes": [...], "mensagens": n}."""
    from .correcoes import vigentes

    correcoes = vigentes(caso)
    brutas = []
    for doc in caso.documentos():
        for m in mensagens_de_email(doc) + mensagens_de_chat(doc):
            m["localizador"] = localizador(doc, [m["pagina"]] if m["pagina"] else None)
            m["caminho"] = doc["arquivo"]["caminhos"][0]
            m["documento_id"] = doc["documento_id"]
            # id estável, do conteúdo bruto (antes das correções)
            base = f"{m['caminho']}|{m['pagina']}|{m['data']}|{m['de']}|{m['para']}|{m['cc']}|{m['assunto']}"
            m["id"] = hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
            m["correcoes"] = {}
            m["de_texto"], m["para_texto"] = _como_texto([m["de"]]), _como_texto(m["para"] + m["cc"])
            for campo in ("de", "para", "data", "assunto"):
                c = correcoes.get((m["id"], campo))
                if not c:
                    continue
                valor = c["valor_proposto"]
                if campo == "de":
                    pessoas_ = participantes(valor)
                    if pessoas_:
                        m["de"] = pessoas_[0]
                elif campo == "para":
                    m["para"], m["cc"] = participantes(valor), []
                else:
                    m[campo] = valor
                m["correcoes"][campo] = {"conferencia": c["conferencia_maquina"], "anterior": c["valor_anterior"]}
            if m["correcoes"]:
                m["de_texto"], m["para_texto"] = _como_texto([m["de"]]), _como_texto(m["para"] + m["cc"])
            brutas.append(m)

    # identidades: endereço quando houver; o nome sem endereço herda o endereço já visto com o mesmo nome
    endereco_do_nome: dict[str, str] = {}
    for m in brutas:
        for nome, end in [m["de"], *m["para"], *m["cc"]]:
            if end and nome:
                endereco_do_nome.setdefault(chave(nome), end)

    pessoas: dict[str, dict] = {}

    def ident(nome: str, end: str | None) -> str:
        end = end or endereco_do_nome.get(chave(nome))
        pid = end or "nome:" + chave(nome)
        p = pessoas.setdefault(pid, {"id": pid, "nomes": set(), "endereco": end, "organizacao": organizacao(end),
                                     "enviadas": 0, "recebidas": 0})
        if nome:
            p["nomes"].add(nome)
        return pid

    pares: dict[tuple, dict] = defaultdict(lambda: {"mensagens": [], "copia": 0})
    for m in brutas:
        de = ident(*m["de"])
        pessoas[de]["enviadas"] += 1
        for destino, em_copia in [(p, False) for p in m["para"]] + [(p, True) for p in m["cc"]]:
            para = ident(*destino)
            if para == de:
                continue
            pessoas[para]["recebidas"] += 1
            par = pares[tuple(sorted((de, para)))]
            par["mensagens"].append({"id": m["id"], "de": de, "para": para, "data": m["data"], "assunto": m["assunto"],
                                     "meio": m["meio"], "copia": em_copia, "localizador": m["localizador"],
                                     "caminho": m["caminho"], "pagina": m["pagina"], "documento_id": m["documento_id"],
                                     "correcoes": m["correcoes"], "de_texto": m["de_texto"],
                                     "para_texto": m["para_texto"]})
            par["copia"] += em_copia

    def rotulo(pid):
        p = pessoas[pid]
        return sorted(p["nomes"], key=len, reverse=True)[0] if p["nomes"] else (p["endereco"] or pid)

    lista_pares = []
    for (a, b), par in pares.items():
        datas = sorted(x["data"] for x in par["mensagens"] if x["data"])
        oa, ob = pessoas[a]["organizacao"], pessoas[b]["organizacao"]
        lista_pares.append({
            "a": a, "b": b, "rotulo_a": rotulo(a), "rotulo_b": rotulo(b), "total": len(par["mensagens"]),
            "em_copia": par["copia"], "primeira": datas[0] if datas else "", "ultima": datas[-1] if datas else "",
            "organizacao_a": oa, "organizacao_b": ob, "entre_organizacoes": bool(oa and ob and oa != ob),
            "documentos": sorted({x["localizador"].rsplit(", p.", 1)[0] for x in par["mensagens"]}),
            "mensagens": sorted(par["mensagens"], key=lambda x: x["data"] or "9999"),
        })
    lista_pares.sort(key=lambda p: (-p["total"], p["rotulo_a"]))

    orgs: dict[tuple, dict] = defaultdict(lambda: {"total": 0, "pares": 0})
    for p in lista_pares:
        if p["entre_organizacoes"]:
            o = orgs[tuple(sorted((p["organizacao_a"], p["organizacao_b"])))]
            o["total"] += p["total"]
            o["pares"] += 1
    entre = sorted(({"organizacoes": list(k), **v} for k, v in orgs.items()), key=lambda x: -x["total"])
    for p in pessoas.values():
        p["nomes"] = sorted(p["nomes"])
        p["rotulo"] = rotulo(p["id"])
    return {"pessoas": pessoas, "pares": lista_pares, "entre_organizacoes": entre, "mensagens": len(brutas)}


def grafo_dot(teia: dict, maximo_pares: int = 30) -> str:
    """Grafo em DOT (Graphviz) dos pares mais frequentes; linhas vermelhas entre organizações."""
    pares = teia["pares"][:maximo_pares]
    usados = {x for p in pares for x in (p["a"], p["b"])}
    cores = ["#dbeafe", "#dcfce7", "#fef9c3", "#fce7f3", "#ede9fe", "#ffedd5", "#e0f2fe", "#f1f5f9"]
    orgs = sorted({teia["pessoas"][u]["organizacao"] or "" for u in usados})
    cor_org = {o: cores[i % len(cores)] for i, o in enumerate(orgs)}

    def esc(s):
        return s.replace("\\", "\\\\").replace('"', "'")

    linhas = ['graph teia {', '  graph [overlap=false, splines=true, fontname="Helvetica"];',
              '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];',
              '  edge [fontname="Helvetica", fontsize=9];']
    for u in sorted(usados):
        p = teia["pessoas"][u]
        legenda = esc(p["rotulo"]) + (f"\\n{esc(p['organizacao'])}" if p["organizacao"] else "")
        linhas.append(f'  "{esc(u)}" [label="{legenda}", fillcolor="{cor_org[p["organizacao"] or ""]}"];')
    maior = max((p["total"] for p in pares), default=1)
    for p in pares:
        largura = 1 + 4 * p["total"] / maior
        cor = "#dc2626" if p["entre_organizacoes"] else "#64748b"
        linhas.append(f'  "{esc(p["a"])}" -- "{esc(p["b"])}" [label="{p["total"]}", penwidth={largura:.1f}, color="{cor}"];')
    linhas.append("}")
    return "\n".join(linhas)
