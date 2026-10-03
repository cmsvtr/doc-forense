"""Relatório Word de apoio ao analista (guia de leitura para a nota técnica, não é anexo)."""

import re
from collections import defaultdict
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from . import __version__
from . import termos_cartel as T
from .caso import Caso, agora, ler_json
from .regex_br import extrair_datas
from .sei import localizador
from .texto import normalizar, trecho
from .triagem import ler_triagem

MAX_PRIORIDADES = 25
MAX_DATAS_CONTEXTO = 300

_FORTES = [re.compile(p) for termos in T.CATEGORIAS.values() for p, peso in termos if peso >= 2]


# ------------------------------------------------------------------ helpers de formatação

def _sombrear(celula, cor_hex: str):
    tc_pr = celula._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), cor_hex)
    tc_pr.append(shd)


def _tabela(doc, cabecalho: list[str], linhas: list[list], larguras_cm: list[float] | None = None, fonte=8):
    t = doc.add_table(rows=1, cols=len(cabecalho))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(cabecalho):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold = True
        r.font.size = Pt(fonte)
        _sombrear(c, "D9E2F3")
    for linha in linhas:
        cells = t.add_row().cells
        for i, v in enumerate(linha):
            cells[i].text = ""
            r = cells[i].paragraphs[0].add_run("" if v is None else str(v))
            r.font.size = Pt(fonte)
    if larguras_cm:
        for row in t.rows:
            for i, w in enumerate(larguras_cm):
                row.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


def _aviso(doc, texto: str):
    t = doc.add_table(rows=1, cols=1)
    t.style = "Table Grid"
    c = t.rows[0].cells[0]
    _sombrear(c, "FFF2CC")
    c.text = ""
    r = c.paragraphs[0].add_run(texto)
    r.font.size = Pt(9)
    doc.add_paragraph()


def _paginas(lista) -> str:
    return ", ".join(map(str, lista))


# ------------------------------------------------------------------ seções

def _visao_geral(doc, docs, manifesto):
    total_pag = sum(len(d["paginas"]) for d in docs)
    ocr = sum(1 for d in docs for p in d["paginas"] if p["metodo"] == "ocr")
    baixa = sum(1 for d in docs for p in d["paginas"] if p.get("confianca_baixa"))
    erros = sum(1 for d in docs if d["status"] != "ok")
    datas_email = sorted(m["data_iso"][:10] for d in docs for m in d.get("emails", []) if m.get("data_iso"))
    doc.add_heading("1. Visão geral", level=1)
    itens = [
        f"Documentos distintos: {len(docs)} (PDF: {sum(1 for d in docs if d['arquivo']['tipo'] == 'pdf')}, "
        f"HTML: {sum(1 for d in docs if d['arquivo']['tipo'] == 'html')})",
        f"Páginas: {total_pag}, das quais {ocr} lidas por OCR ({baixa} com confiança baixa)",
        f"Documentos com erro ou extração parcial: {erros}",
        f"Mensagens de e-mail identificadas: {sum(len(d.get('emails', [])) for d in docs)}",
    ]
    if datas_email:
        itens.append(f"Período coberto pelos e-mails: {datas_email[0]} a {datas_email[-1]}")
    if manifesto and manifesto.get("arquivos_ignorados"):
        itens.append(f"Arquivos ignorados por formato não suportado: {len(manifesto['arquivos_ignorados'])} (ver seção 3)")
    for i in itens:
        doc.add_paragraph(i, style="List Bullet")


def _prioridades(doc, triagem):
    doc.add_heading("2. Por onde começar: prioridades de leitura", level=1)
    doc.add_paragraph(
        "Documentos ordenados pela pontuação da triagem. A pontuação soma termos típicos de condutas "
        "colusivas (com peso) e sinais estruturais, como vários CNPJs ou domínios de e-mail no mesmo documento. "
        "Serve para decidir a ordem de leitura, não para concluir nada. Documento com pontuação baixa pode ser "
        "decisivo (por exemplo, linguagem cifrada).")
    relevantes = [r for r in triagem["documentos"] if r["pontuacao"] > 0][:MAX_PRIORIDADES]
    if not relevantes:
        doc.add_paragraph("Nenhum documento pontuou na triagem.")
        return
    for r in relevantes:
        h = doc.add_heading(f"#{r['posicao']} — {r['arquivo']}  ({r['pontuacao']} pontos)", level=2)
        h.runs[0].font.size = Pt(11)
        p = doc.add_paragraph()
        p.add_run("Citar como: ").bold = True
        p.add_run(r.get("localizador") or r["arquivo"])
        p.add_run("  ·  Arquivo: ").bold = True
        p.add_run(r["caminho"])
        if r["bonus"]:
            p = doc.add_paragraph()
            p.add_run("Sinais estruturais: ").bold = True
            p.add_run("; ".join(r["bonus"]))
        for cat, achados in r["categorias"].items():
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(f"{cat}: ").bold = True
            p.add_run("; ".join(
                f"“{a['trechos'][0]['termo'] if a['trechos'] else a['padrao']}” ×{a['ocorrencias']} (p. {_paginas(a['paginas'])})"
                for a in achados))
        for t in _trechos_distintos(r, maximo=3):
            q = doc.add_paragraph(style="Quote")
            q.add_run(f"p. {t['pagina']}: ").bold = True
            q.add_run(t["trecho"])


def _trechos_distintos(r: dict, maximo: int) -> list[dict]:
    """Trechos de termos fortes, sem repetir a mesma região do texto."""
    escolhidos: list[dict] = []
    candidatos = [t for achados in r["categorias"].values() for a in achados if a["peso"] >= 2 for t in a["trechos"]]
    for t in candidatos:
        if any(t["pagina"] == e["pagina"] and abs(t.get("posicao", 0) - e.get("posicao", 0)) < 240 for e in escolhidos):
            continue
        escolhidos.append(t)
        if len(escolhidos) == maximo:
            break
    return escolhidos


def _qualidade(doc, docs, manifesto):
    doc.add_heading("3. Pontos de atenção na extração", level=1)
    doc.add_paragraph(
        "Antes de citar um trecho lido por OCR, confira-o na imagem original, sobretudo nas páginas abaixo. "
        "Erros de OCR em números (valores, datas, CNPJs) são comuns.")
    linhas = []
    for d in docs:
        for a in d["alertas"]:
            linhas.append([d["arquivo"]["nome"], a])
        for e in d["erros"]:
            if "Traceback" not in e:
                linhas.append([d["arquivo"]["nome"], f"Erro: {e}"])
    duplicados = [d for d in docs if len(d["arquivo"]["caminhos"]) > 1]
    for d in duplicados:
        linhas.append([d["arquivo"]["nome"], "Arquivo idêntico (mesmo hash) em: " + "; ".join(d["arquivo"]["caminhos"])])
    for ign in (manifesto or {}).get("arquivos_ignorados", []):
        linhas.append([Path(ign).name, "Formato não suportado; não foi lido (verificar manualmente)."])
    if linhas:
        _tabela(doc, ["Documento", "Ponto de atenção"], linhas, [6, 11])
    else:
        doc.add_paragraph("Nenhum alerta.")


def _linha_do_tempo(doc, docs):
    doc.add_heading("4. Linha do tempo preliminar (sem IA)", level=1)
    doc.add_paragraph(
        "Construída só com dados objetivos: cabeçalhos de e-mail e datas citadas no texto. "
        "A interpretação dos eventos fica para a etapa de análise.")

    doc.add_heading("4.1 Mensagens de e-mail", level=2)
    msgs = sorted(
        ([m.get("data_iso") or "", m.get("de", ""), m.get("para", ""), m.get("assunto", ""), d["arquivo"]["nome"]]
         for d in docs for m in d.get("emails", [])),
        key=lambda x: x[0] or "9999")
    if msgs:
        _tabela(doc, ["Data", "De", "Para", "Assunto", "Documento"],
                [[a.replace("T", " "), b, c, s, f] for a, b, c, s, f in msgs], [2.6, 3.6, 3.6, 4, 3.2])
    else:
        doc.add_paragraph("Nenhum cabeçalho de e-mail identificado.")

    doc.add_heading("4.2 Datas citadas perto de termos relevantes", level=2)
    doc.add_paragraph("Datas que aparecem a até ~300 caracteres de um termo de peso 2 ou mais da triagem.")
    eventos = []
    for d in docs:
        for pg in d["paginas"]:
            original = pg.get("texto") or ""
            norm = normalizar(original)
            for dt in extrair_datas(original):
                janela = norm[max(0, dt["inicio"] - 300): dt["fim"] + 300]
                if any(r.search(janela) for r in _FORTES):
                    eventos.append([dt["data"], localizador(d, [pg["n"]]),
                                    trecho(original, dt["inicio"], dt["fim"], 160)])
    eventos.sort(key=lambda e: e[0])
    if eventos:
        if len(eventos) > MAX_DATAS_CONTEXTO:
            doc.add_paragraph(f"Exibindo {MAX_DATAS_CONTEXTO} de {len(eventos)}; use a busca do aplicativo para o restante.")
        _tabela(doc, ["Data", "Onde", "Contexto"], eventos[:MAX_DATAS_CONTEXTO], [2.2, 4.3, 10.5])
    else:
        doc.add_paragraph("Nenhuma data próxima de termos relevantes.")


def _entidades(doc, docs):
    doc.add_heading("5. Identificadores encontrados (CNPJ, CPF, e-mail, valores)", level=1)
    doc.add_paragraph(
        "Extraídos por padrão com validação de dígito verificador (CNPJ numérico e alfanumérico, CPF). "
        "Ponto de partida para o dramatis personae: confirme a razão social de cada CNPJ em fonte oficial.")
    por_tipo: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for d in docs:
        for tipo, itens in (d.get("entidades") or {}).items():
            if tipo == "datas":
                continue
            for it in itens:
                por_tipo[tipo][it["valor"]].append(localizador(d, it["paginas"]))
    rotulos = {"cnpjs": "5.1 CNPJs", "cpfs": "5.2 CPFs", "emails": "5.3 E-mails", "valores": "5.4 Valores monetários"}
    for tipo, rotulo in rotulos.items():
        doc.add_heading(rotulo, level=2)
        itens = sorted(por_tipo.get(tipo, {}).items(), key=lambda kv: (-len(kv[1]), kv[0]))
        if not itens:
            doc.add_paragraph("Nenhum.")
            continue
        _tabela(doc, ["Valor", "Nº docs", "Onde aparece"],
                [[v, len(onde), "; ".join(onde[:8]) + (" …" if len(onde) > 8 else "")] for v, onde in itens[:200]],
                [4.5, 1.5, 11])


def _anexo_custodia(doc, docs, caso: Caso, manifesto):
    doc.add_page_break()
    doc.add_heading("Anexo A — Inventário e cadeia de custódia", level=1)
    hash_manifesto = None
    arq = caso.raiz / "manifesto.json.sha256"
    if arq.exists():
        hash_manifesto = arq.read_text(encoding="utf-8").split()[0]
    doc.add_paragraph(
        f"Manifesto: {caso.manifesto.name}" + (f" — SHA-256 {hash_manifesto}" if hash_manifesto else "")
        + (f" — gerado em {manifesto['gerado_em']}" if manifesto else ""))
    linhas = []
    for i, d in enumerate(docs, 1):
        ocr = sum(1 for p in d["paginas"] if p["metodo"] == "ocr")
        sei = (d.get("sei") or {}).get("numero") or "—"
        linhas.append([i, "\n".join(d["arquivo"]["caminhos"]), sei, d["arquivo"]["tipo"].upper(), len(d["paginas"]),
                       ocr, d["status"], d["arquivo"]["sha256"]])
    _tabela(doc, ["#", "Arquivo", "SEI", "Tipo", "Pág.", "OCR", "Status", "SHA-256"], linhas,
            [0.7, 4.6, 1.4, 1, 0.9, 0.9, 1.2, 6.3], fonte=7)


def _anexo_metodo(doc, manifesto, triagem):
    doc.add_heading("Anexo B — Método e ferramentas", level=1)
    if manifesto:
        f = manifesto.get("ferramentas", {})
        p = manifesto.get("parametros", {})
        for item in [
            f"Aplicativo doc-forense {manifesto['aplicativo']['versao']} (extrator {manifesto['aplicativo']['extrator']})",
            f"Sistema: {manifesto['sistema']['so']}, Python {manifesto['sistema']['python']}",
            f"OCR: {f.get('tesseract') or 'indisponível'}; idioma {f.get('idioma', p.get('idioma'))}; "
            f"modelo {Path(f.get('traineddata', '')).name or '-'} (SHA-256 {f.get('traineddata_sha256', '-')})",
            f"Renderização de PDF a {p.get('dpi')} dpi; página tratada como digital se tiver ao menos "
            f"{p.get('limiar_texto_digital')} letras/dígitos; alerta de OCR abaixo de {p.get('confianca_baixa')}% de confiança",
            "Bibliotecas: " + ", ".join(f"{k} {v}" for k, v in f.get("bibliotecas", {}).items()),
        ]:
            doc.add_paragraph(item, style="List Bullet")
    if triagem:
        doc.add_paragraph(
            f"Triagem gerada em {triagem['gerado_em']} com a lista de termos de hash {triagem['termos_hash']} "
            "(arquivo forense/termos_cartel.py). Pontos = soma, por termo, de min(ocorrências, "
            f"{T.MAX_OCORRENCIAS_POR_TERMO}) × peso, mais bônus estruturais.", style="List Bullet")
    doc.add_paragraph(
        "O texto extraído de cada documento está em extraido/<id>.json, página a página, com o método usado "
        "(texto digital ou OCR) e a confiança do OCR. Os originais não são alterados; a integridade pode ser "
        "verificada a qualquer momento pelo aplicativo (recalcula os hashes e compara com o manifesto).",
        style="List Bullet")


# ------------------------------------------------------------------ principal

def gerar_relatorio(caso: Caso) -> Path:
    docs = caso.documentos()
    if not docs:
        raise RuntimeError("Nenhum documento processado neste caso.")
    triagem = ler_triagem(caso) or {"documentos": [], "gerado_em": "-", "termos_hash": "-"}
    manifesto = ler_json(caso.manifesto) if caso.manifesto.exists() else None

    doc = Document()
    estilo = doc.styles["Normal"]
    estilo.font.name = "Calibri"
    estilo.font.size = Pt(10)
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.PORTRAIT
    for lado in ("left_margin", "right_margin"):
        setattr(sec, lado, Cm(2))
    sec.top_margin = sec.bottom_margin = Cm(2)

    titulo = doc.add_heading("Relatório de apoio ao analista", level=0)
    titulo.runs[0].font.color.rgb = RGBColor(0x1F, 0x38, 0x64)
    doc.add_paragraph(f"Caso: {caso.nome}  ·  Gerado em {agora()}  ·  doc-forense {__version__}")
    _aviso(doc,
           "DOCUMENTO DE TRABALHO INTERNO. Organiza o material para orientar a leitura e a redação da nota técnica. "
           "Não é prova nem conclusão. Todo trecho deve ser conferido no documento original (arquivo e página indicados), "
           "especialmente os lidos por OCR. A triagem é heurística e pode deixar passar documentos relevantes.")

    _visao_geral(doc, docs, manifesto)
    _prioridades(doc, triagem)
    _qualidade(doc, docs, manifesto)
    _linha_do_tempo(doc, docs)
    _entidades(doc, docs)
    _anexo_custodia(doc, docs, caso, manifesto)
    _anexo_metodo(doc, manifesto, triagem)

    caso.relatorios.mkdir(parents=True, exist_ok=True)
    destino = caso.relatorios / f"relatorio_apoio_{agora()[:19].replace(':', '').replace('-', '')}.docx"
    doc.save(destino)
    caso.registrar("relatorio_gerado", arquivo=caso.relativo(destino))
    return destino
