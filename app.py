"""Interface local (Streamlit) do doc-forense. Inicie com abrir.bat ou: uv run streamlit run app.py"""

import html
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from forense import __version__
from forense.caso import EXTENSOES, Caso
from forense.ocr import sha256_arquivo
from forense.processamento import em_execucao, ler_progresso

RAIZ = Path(__file__).resolve().parent
BASE_CASOS = Path(os.environ.get("FORENSE_CASOS", RAIZ / "casos"))

st.set_page_config(page_title="doc-forense", page_icon="🔎", layout="wide")


# ------------------------------------------------------------------ dados em cache

def versao_dos_dados(caso: Caso) -> float:
    """Muda sempre que um processamento termina (o manifesto é regravado)."""
    return caso.manifesto.stat().st_mtime if caso.manifesto.exists() else 0.0


@st.cache_data(show_spinner="Carregando documentos…")
def documentos(raiz: str, versao: float) -> list[dict]:
    # «versao» entra na chave do cache: muda quando um processamento termina. (Parâmetro com
    # nome iniciado por «_» o Streamlit NÃO usa na chave, e a tela ficava com os dados antigos.)
    return Caso(Path(raiz)).documentos()


@st.cache_data
def triagem(raiz: str, versao: float) -> dict | None:
    from forense.triagem import ler_triagem
    return ler_triagem(Caso(Path(raiz)))


@st.cache_data
def diagnostico():
    from forense.diagnostico import diagnosticar
    return diagnosticar()


def abrir_pasta(p: Path):
    if sys.platform.startswith("win"):
        os.startfile(p)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def destacar(trecho: str) -> str:
    """Escapa o texto do documento (nunca é interpretado como HTML) e realça os termos «assim»."""
    return html.escape(" ".join(trecho.split())).replace("«", "<mark>").replace("»", "</mark>")


# ------------------------------------------------------------------ barra lateral: caso

BASE_CASOS.mkdir(parents=True, exist_ok=True)
with st.sidebar:
    st.title("🔎 doc-forense")
    st.caption(f"v{__version__} · tudo roda neste computador")
    casos = sorted(p.name for p in BASE_CASOS.iterdir() if (p / "originais").is_dir())
    escolhido = st.selectbox("Caso", casos, index=None if not casos else 0, placeholder="Nenhum caso ainda")
    with st.expander("Novo caso", expanded=not casos):
        nome_novo = st.text_input("Nome do caso", placeholder="ex.: PA 08700.000000-2026 Obras")
        if st.button("Criar caso", disabled=not nome_novo.strip()):
            novo = Caso.criar(BASE_CASOS, nome_novo)
            st.success(f"Caso criado: {novo.nome}")
            time.sleep(0.6)
            st.rerun()
    with st.expander("Diagnóstico da instalação"):
        for nome, ok, detalhe in diagnostico():
            st.write(("✅ " if ok else "❌ ") + f"**{nome}**: {detalhe}")

if not escolhido:
    st.info("Crie um caso na barra lateral para começar.")
    st.stop()

caso = Caso(BASE_CASOS / escolhido)
marca = versao_dos_dados(caso)
docs = documentos(str(caso.raiz), marca)
rodando = em_execucao(caso)

st.header(caso.nome)
abas = st.tabs(["1 · Entrada", "2 · Processar", "3 · Triagem", "4 · Busca", "5 · Documento", "6 · Relatório e custódia"])

# ------------------------------------------------------------------ 1. entrada

with abas[0]:
    suportados, ignorados = caso.listar_originais()
    st.write(f"**{len(suportados)}** arquivos PDF/HTML na pasta de originais"
             + (f" · {len(ignorados)} em outros formatos (não serão lidos)" if ignorados else ""))
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("📂 Abrir pasta de originais"):
            abrir_pasta(caso.originais)
    with c2:
        st.code(str(caso.originais), language=None)
    st.caption("Copie os documentos para essa pasta (subpastas são aceitas) ou envie abaixo. "
               "O aplicativo nunca altera os originais.")

    enviados = st.file_uploader("Enviar documentos", type=["pdf", "html", "htm"], accept_multiple_files=True,
                                disabled=rodando)
    if enviados and st.button(f"Adicionar {len(enviados)} arquivo(s) ao caso"):
        destino_dir = caso.originais / "enviados"
        destino_dir.mkdir(exist_ok=True)
        novos = 0
        for arq in enviados:
            destino = destino_dir / Path(arq.name).name
            conteudo = arq.getvalue()
            if destino.exists():
                if destino.read_bytes() == conteudo:
                    continue
                destino = destino.with_name(f"{destino.stem}_{int(time.time())}{destino.suffix}")
            destino.write_bytes(conteudo)
            caso.registrar("arquivo_adicionado", arquivo=caso.relativo(destino), sha256=sha256_arquivo(destino))
            novos += 1
        st.success(f"{novos} arquivo(s) adicionados. Vá para a aba Processar.")

    if ignorados:
        with st.expander("Arquivos em formatos não suportados"):
            st.write("\n".join(f"- {caso.relativo(p)}" for p in ignorados))

# ------------------------------------------------------------------ 2. processar

with abas[1]:
    suportados, _ = caso.listar_originais()
    st.write(f"Originais: **{len(suportados)}** · Já extraídos: **{len(docs)}**")
    st.caption("O processamento roda em segundo plano: pode fechar o navegador. Se for interrompido, "
               "basta processar de novo; o que já foi feito não é refeito.")
    with st.expander("Opções avançadas"):
        forcar_ocr = st.checkbox("Forçar OCR em todas as páginas (mais lento)")
        nucleos = os.cpu_count() or 2
        workers = st.slider("Processos em paralelo", 1, nucleos, max(1, nucleos // 2))

    if st.button("▶ Processar documentos", type="primary", disabled=rodando or not suportados):
        cmd = [sys.executable, "-m", "forense", "processar", str(caso.raiz), "--workers", str(workers)]
        if forcar_ocr:
            cmd.append("--forcar-ocr")
        log = open(caso.log_execucao, "a", encoding="utf-8")
        opcoes = {"cwd": RAIZ, "stdout": log, "stderr": subprocess.STDOUT,
                  "env": {**os.environ, "PYTHONIOENCODING": "utf-8"}}
        if sys.platform.startswith("win"):
            opcoes["creationflags"] = 0x08000000 | 0x00000200  # sem janela, grupo próprio
        else:
            opcoes["start_new_session"] = True
        subprocess.Popen(cmd, **opcoes)
        st.session_state["lancado_em"] = time.time()
        time.sleep(1.5)
        st.rerun()

    @st.fragment(run_every=2)
    def painel_progresso():
        p = ler_progresso(caso)
        recem_lancado = time.time() - st.session_state.get("lancado_em", 0) < 15
        if p and p["estado"] == "executando":
            total = max(p.get("total") or 1, 1)
            st.progress(min(p.get("concluidos", 0) / total, 1.0),
                        text=f"{p['etapa']}: {p.get('concluidos', 0)}/{p.get('total', 0)}"
                             + (f" · {p['atual']}" if p.get("atual") else ""))
        elif recem_lancado and not (p and p["estado"] == "concluido" and p.get("heartbeat", 0) > st.session_state["lancado_em"]):
            st.info("Iniciando…")
        elif p:
            if p["estado"] == "concluido":
                st.success(f"Último processamento concluído. {p.get('resumo', '')}")
                if p.get("heartbeat", 0) > st.session_state.get("visto", 0):
                    st.session_state["visto"] = p["heartbeat"]
                    st.rerun(scope="app")  # recarrega os dados das outras abas
            elif p["estado"] == "interrompido":
                st.warning("O último processamento foi interrompido. Clique em Processar para continuar de onde parou.")
            elif p["estado"] == "falhou":
                st.error(f"O último processamento falhou: {p.get('mensagem')}")
        if caso.log_execucao.exists():
            linhas = caso.log_execucao.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
            st.code("\n".join(linhas) or "(sem registros)", language=None)

    painel_progresso()

# ------------------------------------------------------------------ 3. triagem

with abas[2]:
    t = triagem(str(caso.raiz), marca)
    if not t:
        st.info("Processe os documentos para gerar a triagem.")
    else:
        st.caption(t["aviso"] + " A lista de termos fica em forense/termos_cartel.py.")
        linhas = [{
            "#": r["posicao"], "Documento": r["arquivo"], "Pontos": r["pontuacao"],
            "Pontos/mil palavras": r["densidade_por_mil_palavras"],
            "Sinais": ", ".join(r["categorias"].keys()) or "—",
        } for r in t["documentos"]]
        st.dataframe(pd.DataFrame(linhas), hide_index=True, use_container_width=True, height=320)
        nomes = [r["arquivo"] for r in t["documentos"] if r["pontuacao"] > 0]
        if nomes:
            sel = st.selectbox("Ver por que o documento pontuou", nomes)
            r = next(x for x in t["documentos"] if x["arquivo"] == sel)
            if r["bonus"]:
                st.write("**Sinais estruturais:** " + "; ".join(r["bonus"]))
            for cat, achados in r["categorias"].items():
                st.markdown(f"**{cat}**")
                for a in achados:
                    for tr in a["trechos"]:
                        st.markdown(f"<div style='margin-left:1em'>p. {tr['pagina']} · peso {a['peso']} · "
                                    f"{destacar(tr['trecho'].replace(tr['termo'], '«' + tr['termo'] + '»', 1))}</div>",
                                    unsafe_allow_html=True)

# ------------------------------------------------------------------ 4. busca

with abas[3]:
    from forense.indice import buscar

    q = st.text_input("Buscar em todos os documentos",
                      placeholder='ex.: cobertura   ·   "tabela única"   ·   combin*   ·   rodízio OU revezamento')
    st.caption("Acentos e maiúsculas não importam. Aspas = frase exata; * no fim = prefixo; OU = qualquer um dos termos.")
    if q:
        resultados = buscar(caso, q)
        st.write(f"{len(resultados)} resultado(s){' (limitado a 200)' if len(resultados) == 200 else ''}")
        for r in resultados:
            st.markdown(f"**{html.escape(r['localizador'])}, p. {r['pagina']}** — <span style='color:gray'>{html.escape(r['caminho'])}</span>"
                        f"<br>{destacar(r['trecho'])}", unsafe_allow_html=True)

# ------------------------------------------------------------------ 5. documento

with abas[4]:
    if not docs:
        st.info("Nenhum documento extraído ainda.")
    else:
        nomes = {f"{d['arquivo']['nome']}  ·  {d['documento_id']}": d for d in docs}
        d = nomes[st.selectbox("Documento", list(nomes))]
        a = d["arquivo"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Páginas", len(d["paginas"]))
        c2.metric("Páginas por OCR", sum(1 for p in d["paginas"] if p["metodo"] == "ocr"))
        c3.metric("Status", d["status"])
        c4.metric("Alertas", len(d["alertas"]))
        st.write(f"**Arquivo(s):** {'; '.join(a['caminhos'])}  \n**SHA-256:** `{a['sha256']}`")
        for al in d["alertas"]:
            st.warning(al)
        if d.get("emails"):
            st.markdown("**Mensagens de e-mail**")
            st.dataframe(pd.DataFrame(d["emails"]), hide_index=True, use_container_width=True)
        ent = d.get("entidades") or {}
        if any(ent.get(k) for k in ("cnpjs", "cpfs", "emails", "valores")):
            with st.expander("Identificadores (CNPJ, CPF, e-mail, valores)"):
                for k, rot in (("cnpjs", "CNPJs"), ("cpfs", "CPFs"), ("emails", "E-mails"), ("valores", "Valores")):
                    if ent.get(k):
                        st.write(f"**{rot}:** " + "; ".join(f"{i['valor']} (p. {', '.join(map(str, i['paginas']))})" for i in ent[k]))
        if d.get("metadados_pdf"):
            with st.expander("Metadados do PDF"):
                st.json(d["metadados_pdf"])
        n = st.number_input("Página", 1, max(len(d["paginas"]), 1), 1) if len(d["paginas"]) > 1 else 1
        if d["paginas"]:
            pg = d["paginas"][n - 1]
            info = {"texto_digital": "texto digital", "ocr": "OCR", "html": "HTML", "erro": "falha"}[pg["metodo"]]
            if pg.get("confianca_media") is not None:
                info += f" · confiança {pg['confianca_media']:.0f}%"
            st.caption(f"Página {pg['n']} · {info}")
            st.text(pg.get("texto") or "(sem texto)")

# ------------------------------------------------------------------ 6. relatório e custódia

with abas[5]:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Relatório de apoio (Word)")
        st.caption("Roteiro para orientar a leitura e a nota técnica. Documento interno, não é anexo.")
        if st.button("Gerar relatório", disabled=not docs or rodando):
            from forense.relatorio import gerar_relatorio
            with st.spinner("Gerando…"):
                st.session_state["relatorio"] = str(gerar_relatorio(caso))
        rel = st.session_state.get("relatorio")
        if rel and Path(rel).exists():
            st.download_button("⬇ Baixar relatório", Path(rel).read_bytes(), file_name=Path(rel).name,
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            st.caption(f"Salvo também em {rel}")
    with c2:
        st.subheader("Cadeia de custódia")
        st.caption("Recalcula os hashes dos originais e das extrações e compara com o manifesto.")
        if st.button("Verificar integridade", disabled=rodando):
            r = caso.verificar_integridade()
            if r["ok"]:
                st.success(f"Integridade OK: {r['conferidos']} originais conferidos.")
            else:
                st.error("Problemas encontrados:")
                st.write("\n".join(f"- {p}" for p in r["problemas"]))
        if caso.manifesto.exists():
            arq = caso.raiz / "manifesto.json.sha256"
            if arq.exists():
                st.write(f"SHA-256 do manifesto: `{arq.read_text(encoding='utf-8').split()[0]}`")
    st.subheader("Exportar para a skill sg-nt:instrucao")
    st.caption("Gera o corpus (texto e caixas do OCR) no formato da Fase 3 da skill, para ela não refazer o OCR.")
    if st.button("Exportar corpus sg-nt", disabled=not docs or rodando):
        from forense.exportar_sgnt import exportar
        r = exportar(caso)
        st.success(f"{r['arquivos_txt']} arquivos de texto e {r['paginas_com_caixas']} páginas com caixas de OCR "
                   f"em {r['pasta']}. Instruções no LEIA-ME.txt da pasta.")

    with st.expander("Registro de auditoria (últimos 50 eventos)"):
        ev = caso.eventos()[-50:][::-1]
        if ev:
            st.dataframe(pd.DataFrame([{"quando": e["quando"], "usuário": e["usuario"], "evento": e["evento"],
                                        "detalhes": {k: v for k, v in e.items() if k not in ("quando", "usuario", "evento")}}
                                       for e in ev]), hide_index=True, use_container_width=True)
