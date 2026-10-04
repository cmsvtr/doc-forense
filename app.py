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


@st.cache_data(ttl=30)
def situacao_ia():
    from forense.ia import situacao
    return situacao()


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


def botao_abrir(caso: Caso, relativo: str, pagina: int | None, chave: str, rotulo: str | None = None):
    """Botão que abre o original no programa do computador, na página quando é PDF."""
    from forense.abrir import abrir, caminho_seguro

    if not relativo.lower().endswith(".pdf"):
        pagina = None  # HTML não tem página
    if st.button(rotulo or (f"📄 Abrir p. {pagina}" if pagina else "📄 Abrir original"), key=chave):
        try:
            como = abrir(caminho_seguro(caso.originais, relativo, caso.raiz), pagina)
            st.toast(f"Abrindo {Path(relativo).name} {como}")
        except (OSError, PermissionError) as e:
            st.error(f"Não consegui abrir: {e}")


def lancar_em_segundo_plano(caso: Caso, argumentos: list[str]):
    """Roda «python -m forense …» como processo separado: fechar o navegador não interrompe."""
    cmd = [sys.executable, "-m", "forense", *argumentos]
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
    if casos:
        with st.expander("Excluir caso"):
            st.caption("Manda a pasta do caso inteira (originais copiados, extrações, análises e relatórios) para a "
                       "**Lixeira** do Windows, de onde ainda pode ser recuperada. Os autos de origem, fora do app, "
                       "não são tocados. Fica registrado em casos/_excluidos.jsonl.")
            alvo_exc = st.selectbox("Caso a excluir", casos, index=None, placeholder="Escolha", key="exc_caso")
            confirma = st.text_input("Digite o nome do caso para confirmar", key="exc_conf")
            if st.button("🗑️ Excluir caso", disabled=not alvo_exc or confirma.strip() != alvo_exc):
                from forense.caso import excluir_caso
                try:
                    excluir_caso(BASE_CASOS, Caso(BASE_CASOS / alvo_exc))
                    st.success(f"Caso «{alvo_exc}» enviado para a Lixeira.")
                    for k in ("exc_caso", "exc_conf"):
                        st.session_state.pop(k, None)
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()
                except (OSError, RuntimeError) as e:
                    st.error(str(e))
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
abas = st.tabs(["1 · Entrada", "2 · Processar", "3 · Triagem", "4 · Busca e perguntas", "5 · Documento",
                "6 · IA e revisão", "7 · Relatório e custódia"])

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
    st.markdown(
        "**Recomendado:** abra a pasta acima e **copie as pastas dos autos como estão**, com as subpastas. "
        "O nome da pasta de anexo traz o número SEI dos arquivos de dentro (o «Doc. 1.PDF» de um anexo "
        "só é citável como «SEI nº …, Doc. 1» se a pasta vier junto). O aplicativo nunca altera os originais.")

    sem_origem = caso.sem_pasta_de_origem()
    if sem_origem:
        st.warning(
            f"{len(sem_origem)} arquivo(s) «Doc. N» estão sem a pasta de anexo que dá o número SEI "
            f"(ex.: {caso.relativo(sem_origem[0])}). Sem ela, o relatório não consegue citá-los como "
            "«SEI nº …, Doc. N». Para corrigir: apague esses arquivos da pasta de originais, copie as "
            "pastas dos autos com as subpastas e clique em Processar. O OCR já feito é reaproveitado "
            "(o app reconhece cada arquivo pelo conteúdo), então não leva horas de novo.")

    st.markdown("**Importar uma pasta do computador** (copia com as subpastas, em segundo plano; a pasta de "
                "origem não é alterada):")
    c_esc, c_cam = st.columns([1, 3])
    with c_esc:
        if st.button("📁 Escolher pasta…", disabled=rodando):
            from forense.importar import escolher_pasta
            with st.spinner("Escolha a pasta na janela que abriu (ela pode estar atrás do navegador)…"):
                escolhida = escolher_pasta()
            if escolhida:
                st.session_state["origem_importar"] = escolhida
            else:
                st.info("Nenhuma pasta escolhida. Se a janela não abriu, cole o caminho ao lado.")
    with c_cam:
        origem_txt = st.text_input("Caminho da pasta", key="origem_importar",
                                   placeholder=r"ex.: C:\Users\voce\Documents\SEI_08700.000000_2026-00",
                                   label_visibility="collapsed")
    if origem_txt and st.button("⬇ Importar esta pasta para o caso", type="primary", disabled=rodando):
        from forense.importar import validar_origem
        try:
            validar_origem(caso, Path(origem_txt.strip().strip('"')))
            lancar_em_segundo_plano(caso, ["importar", str(caso.raiz), origem_txt.strip().strip('"')])
        except (OSError, ValueError) as e:
            st.error(str(e))
    st.caption("O progresso aparece na aba Processar. Depois da importação, clique em Processar.")

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
        lancar_em_segundo_plano(caso, ["processar", str(caso.raiz), "--workers", str(workers)]
                                + (["--forcar-ocr"] if forcar_ocr else []))

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
            "#": r["posicao"], "Documento": r["arquivo"],
            "Prioridade": ", ".join(r.get("motivos_prioridade", [])) or "—",
            "Pontos": r["pontuacao"], "Pontos/mil palavras": r["densidade_por_mil_palavras"],
            "Sinais": ", ".join(r["categorias"].keys()) or "—",
        } for r in t["documentos"]]
        st.dataframe(pd.DataFrame(linhas), hide_index=True, use_container_width=True, height=320)
        nomes = [r["arquivo"] for r in t["documentos"] if r["pontuacao"] > 0 or r.get("prioritario")]
        if nomes:
            sel = st.selectbox("Ver por que o documento pontuou", nomes)
            r = next(x for x in t["documentos"] if x["arquivo"] == sel)
            botao_abrir(caso, r["caminho"], None, f"tri_doc_{r['documento_id']}")
            if r.get("motivos_prioridade"):
                st.write("**Prioridade:** " + ", ".join(r["motivos_prioridade"]))
                if r.get("empresas_citadas"):
                    st.caption("Empresas reconhecidas: " + "; ".join(r["empresas_citadas"]))
                if r.get("pessoas_citadas"):
                    st.caption("Pessoas reconhecidas: " + "; ".join(r["pessoas_citadas"]))
            if r["bonus"]:
                st.write("**Sinais estruturais:** " + "; ".join(r["bonus"]))
            for cat, achados in r["categorias"].items():
                st.markdown(f"**{cat}**")
                for ia, a in enumerate(achados):
                    for it, tr in enumerate(a["trechos"]):
                        c_txt, c_bt = st.columns([6, 1])
                        c_txt.markdown(f"<div style='margin-left:1em'>p. {tr['pagina']} · peso {a['peso']} · "
                                       f"{destacar(tr['trecho'].replace(tr['termo'], '«' + tr['termo'] + '»', 1))}</div>",
                                       unsafe_allow_html=True)
                        with c_bt:
                            botao_abrir(caso, r["caminho"], tr["pagina"],
                                        f"tri_{r['documento_id']}_{cat}_{ia}_{it}")

# ------------------------------------------------------------------ 4. busca e perguntas

with abas[3]:
    from forense.indice import buscar

    modo_busca = st.radio("Modo", ["Por palavra", "Pergunta (palavra + significado)"], horizontal=True,
                          label_visibility="collapsed")
    if modo_busca == "Por palavra":
        q = st.text_input("Buscar em todos os documentos",
                          placeholder='ex.: cobertura   ·   "tabela única"   ·   combin*   ·   rodízio OU revezamento')
        st.caption("Acentos e maiúsculas não importam. Aspas = frase exata; * no fim = prefixo; OU = qualquer um dos termos.")
        if q:
            resultados = buscar(caso, q)
            st.write(f"{len(resultados)} resultado(s){' (limitado a 200)' if len(resultados) == 200 else ''}")
            for i, r in enumerate(resultados):
                c_txt, c_bt = st.columns([6, 1])
                c_txt.markdown(f"**{html.escape(r['localizador'])}, p. {r['pagina']}** — <span style='color:gray'>{html.escape(r['caminho'])}</span>"
                               f"<br>{destacar(r['trecho'])}", unsafe_allow_html=True)
                with c_bt:
                    botao_abrir(caso, r["caminho"], r["pagina"], f"busca_{i}_{r['doc_id']}_{r['pagina']}")
    else:
        from forense.perguntas import responder
        from forense.vetores import buscar_hibrida
        from forense.vetores import situacao as situacao_vetores

        sit = situacao_ia()
        sv = situacao_vetores(caso)
        if not sit["ativo"]:
            st.warning("A IA local não está ativa: a pergunta usa só a busca por palavra.")
        elif not sit.get("modelo_vetores_baixado"):
            st.warning(f"O modelo da busca por significado ({sit.get('modelo_vetores')}) não está baixado: rode o "
                       "instalar_ia.bat. Até lá, a pergunta usa só a busca por palavra.")
        elif sv["documentos"] < sv["total"]:
            st.info(f"Busca por significado preparada para {sv['documentos']} de {sv['total']} documento(s).")
            if st.button("Preparar busca por significado", disabled=rodando):
                lancar_em_segundo_plano(caso, ["indexar-vetores", str(caso.raiz)])
            st.caption("Roda em segundo plano (progresso na aba Processar). Precisa ser feito uma vez, e de novo "
                       "só para documentos novos.")
        pergunta = st.text_input("Pergunte aos documentos",
                                 placeholder="ex.: quem combinou a divisão dos lotes?  ·  houve contato sobre preços antes do pregão?")
        st.caption("Mostra primeiro as passagens encontradas, que são o que vale. A resposta da IA é opcional, "
                   "usa só essas passagens, e cada afirmação traz o trecho conferido no documento.")
        if pergunta:
            with st.spinner("Buscando…"):
                achadas = buscar_hibrida(caso, pergunta)
            if not achadas:
                st.info("Nada encontrado.")
            else:
                if st.button("🤖 Responder com a IA (usa só as passagens abaixo)",
                             disabled=not (sit["ativo"] and sit["modelo_baixado"])):
                    with st.spinner("A IA está lendo as passagens; na CPU isso pode levar alguns minutos…"):
                        st.session_state["resposta"] = responder(caso, pergunta, achadas, sit["modelo"])
                resp = st.session_state.get("resposta")
                if resp and resp["pergunta"] == pergunta:
                    with st.container(border=True):
                        if not resp["responde"]:
                            st.info("Os documentos encontrados não respondem a essa pergunta com segurança.")
                        for k, a in enumerate(resp["afirmacoes"]):
                            st.markdown(f"**{html.escape(a['afirmacao_ia'])}**")
                            c_txt, c_bt = st.columns([6, 1])
                            c_txt.markdown(f"<blockquote>{html.escape(' '.join(a['trecho_fonte'].split()))}</blockquote>"
                                           f"<span style='color:gray'>{html.escape(a['localizador'])}</span>",
                                           unsafe_allow_html=True)
                            with c_bt:
                                botao_abrir(caso, a["caminho"], a["pagina"], f"resp_{k}")
                        if resp["descartadas"]:
                            st.caption(f"{resp['descartadas']} afirmação(ões) da IA descartada(s): o trecho citado não estava nas passagens.")
                        st.caption("A frase em negrito é da IA; o trecho abaixo dela é o documento. Confira na fonte.")
                st.write(f"{len(achadas)} passagem(ns), da mais para a menos relevante:")
                for i, r in enumerate(achadas):
                    origem = " + ".join({"palavra": "palavra", "significado": "significado"}[o] for o in r["origens"])
                    c_txt, c_bt = st.columns([6, 1])
                    c_txt.markdown(f"**{html.escape(r['localizador'])}** <span style='color:gray'>· achado por {origem}</span>"
                                   f"<br>{html.escape(' '.join(r['passagem'].split()))}", unsafe_allow_html=True)
                    with c_bt:
                        botao_abrir(caso, r["caminho"], r["pagina"], f"hib_{i}_{r['doc_id']}_{r['pagina']}")

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
        from forense.sei import localizador
        sei = d.get("sei") or {}
        if sei.get("numero"):
            origem = {"nome do arquivo": "do nome do arquivo", "pasta de anexo": "da pasta de anexo",
                      "cabeçalho": "do cabeçalho do documento"}.get(sei.get("fonte"), sei.get("fonte"))
            ident = f"SEI {sei['numero']}, tirado {origem}"
            if sei.get("documento_n"):
                ident += f"; Documento {sei['documento_n']} do anexo"
        else:
            ident = "nenhum número SEI identificado"
        st.write(f"**Citar como:** {localizador(d)}  \n**Identificação:** {ident}  \n"
                 f"**Arquivo(s):** {'; '.join(a['caminhos'])}  \n**SHA-256:** `{a['sha256']}`")
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
            c_info, c_bt = st.columns([4, 1])
            c_info.caption(f"Página {pg['n']} · {info}")
            with c_bt:
                botao_abrir(caso, a["caminhos"][0], pg["n"] if a["tipo"] == "pdf" else None,
                            f"doc_{d['documento_id']}_{pg['n']}",
                            rotulo=f"📄 Abrir original na p. {pg['n']}" if a["tipo"] == "pdf" else "📄 Abrir original")
            st.text(pg.get("texto") or "(sem texto)")

# ------------------------------------------------------------------ 6. IA e revisão

def versao_da_analise(caso: Caso) -> float:
    arquivos = list((caso.analise / "ia").glob("*.json")) if (caso.analise / "ia").is_dir() else []
    arquivos.append(caso.analise / "revisao.json")
    return max((a.stat().st_mtime for a in arquivos if a.exists()), default=0.0)


@st.cache_data
def carregar_achados(raiz: str, versao: float) -> list[dict]:
    from forense.analise_ia import achados_do_caso
    return achados_do_caso(Caso(Path(raiz)))


ICONE = {"pessoas": "👤", "empresas": "🏢", "eventos": "📅"}
STATUS = {"pendente": "⏳ pendente", "validado": "✅ validado", "rejeitado": "❌ rejeitado"}


def resumo_achado(a: dict) -> str:
    d = a["dados"]
    if a["tipo"] == "pessoas":
        extra = ", ".join(x for x in (d.get("cargo"), d.get("empresa")) if x)
        return d["nome"] + (f" — {extra}" if extra else "")
    if a["tipo"] == "empresas":
        return d["nome"] + (f" (CNPJ {d['cnpj']})" if d.get("cnpj") else "")
    return f"{d.get('data') or 'sem data'} · {d['categoria']}"


with abas[5]:
    from forense.analise_ia import PALAVRAS_POR_TRECHO, marcar
    from forense.consolidacao import dramatis_personae, linha_do_tempo

    sit = situacao_ia()
    if not sit["ativo"]:
        st.warning("A IA local não está ativa. Rode o instalar_ia.bat ou abra o Ollama pelo menu Iniciar.")
    elif not sit["modelo_baixado"]:
        st.warning(f"O modelo {sit['modelo']} não está baixado. Rode o instalar_ia.bat.")
    else:
        st.caption(f"IA local: Ollama {sit['versao']}, modelo {sit['modelo']}. Roda neste computador; "
                   "nada é enviado para fora.")
    st.caption("A IA propõe; a máquina confere cada trecho no documento e descarta o que não encontra; "
               "você valida. Dramatis personae, linha do tempo e relatório usam só o que você validar.")

    sub = st.tabs(["Analisar", "Revisar achados", "Dramatis personae", "Linha do tempo"])
    achados = carregar_achados(str(caso.raiz), versao_da_analise(caso))

    with sub[0]:
        t = triagem(str(caso.raiz), marca)
        ordem = (t or {}).get("documentos", [])
        if not ordem:
            st.info("Processe os documentos primeiro.")
        else:
            modo = st.radio("Quais documentos", ["Os primeiros da triagem", "Escolher documentos"], horizontal=True)
            argumentos = ["analisar-ia", str(caso.raiz)]
            if modo == "Os primeiros da triagem":
                n = st.number_input("Quantos", 1, len(ordem), min(10, len(ordem)))
                argumentos += ["--primeiros", str(n)]
                escolhidos = ordem[:n]
            else:
                rotulos = {f"#{r['posicao']} {r['arquivo']} ({r['pontuacao']} pts)": r for r in ordem}
                sel = st.multiselect("Documentos", list(rotulos))
                escolhidos = [rotulos[x] for x in sel]
                argumentos += ["--documentos", ",".join(r["documento_id"] for r in escolhidos)]
            palavras_total = sum(r.get("palavras", 0) for r in escolhidos)
            with st.expander("Opções avançadas"):
                palavras = st.slider("Palavras por trecho", 400, 2400, PALAVRAS_POR_TRECHO, 100,
                                     help="Trechos menores: respostas mais precisas, mais chamadas à IA.")
            argumentos += ["--palavras", str(palavras)]
            from forense.ia import ler_velocidade

            n_trechos = max(1, -(-palavras_total // palavras))
            vel = ler_velocidade()
            if vel and vel.get("leitura_tokens_s") and vel.get("escrita_tokens_s"):
                # leitura proporcional ao tamanho do trecho (~1,9 token por palavra); escrita média de ~400 tokens
                seg = n_trechos * (palavras * 1.9 / vel["leitura_tokens_s"] + 400 / vel["escrita_tokens_s"])
                tempo = f"~{seg / 3600:.1f} h" if seg >= 3600 else f"~{max(1, round(seg / 60))} min"
                estimativa = f"Tempo estimado neste computador: **{tempo}** (pela medição de {vel.get('medido_em', '')[:10]})."
            else:
                estimativa = "Rode o testar_ia.bat para estimar o tempo."
            st.write(f"{len(escolhidos)} documento(s), cerca de {palavras_total:,} palavras ".replace(",", ".")
                     + f"(~{n_trechos} trecho(s)). " + estimativa)
            pode = sit["ativo"] and sit["modelo_baixado"] and escolhidos and not rodando
            if st.button("▶ Analisar com IA", type="primary", disabled=not pode):
                lancar_em_segundo_plano(caso, argumentos)
            st.caption("Roda em segundo plano e continua de onde parou se for interrompida. "
                       "O progresso aparece na aba Processar.")

    with sub[1]:
        if not achados:
            st.info("Nenhum achado ainda. Rode a análise na aba ao lado.")
        else:
            contagem = {k: sum(1 for a in achados if a["revisao"]["status"] == k) for k in STATUS}
            st.write(" · ".join(f"{STATUS[k]}: **{v}**" for k, v in contagem.items()))
            c1, c2, c3 = st.columns(3)
            f_status = c1.selectbox("Situação", ["pendente", "validado", "rejeitado", "todos"])
            f_tipo = c2.selectbox("Tipo", ["todos", "pessoas", "empresas", "eventos"])
            docs_achados = sorted({a["localizador"].rsplit(", p.", 1)[0] for a in achados})
            f_doc = c3.selectbox("Documento", ["todos"] + docs_achados)
            lista = [a for a in achados
                     if (f_status == "todos" or a["revisao"]["status"] == f_status)
                     and (f_tipo == "todos" or a["tipo"] == f_tipo)
                     and (f_doc == "todos" or a["localizador"].rsplit(", p.", 1)[0] == f_doc)]
            por_pagina = 15
            paginas_rev = max(1, -(-len(lista) // por_pagina))
            pag = st.number_input(f"Página (de {paginas_rev})", 1, paginas_rev, 1) if paginas_rev > 1 else 1
            for a in lista[(pag - 1) * por_pagina: pag * por_pagina]:
                with st.container(border=True):
                    st.markdown(f"{ICONE[a['tipo']]} **{html.escape(resumo_achado(a))}** · {STATUS[a['revisao']['status']]}")
                    if a["tipo"] == "eventos" and a["dados"].get("descricao_ia"):
                        st.caption(f"Resumo da IA (não é citação): {a['dados']['descricao_ia']}")
                        if a["dados"].get("participantes"):
                            st.caption("Participantes: " + ", ".join(a["dados"]["participantes"]))
                    st.markdown(f"<blockquote>{html.escape(' '.join(a['trecho_fonte'].split()))}</blockquote>"
                                f"<span style='color:gray'>{html.escape(a['localizador'])}</span>", unsafe_allow_html=True)
                    for al in a["alertas"]:
                        st.caption(f"⚠ {al}")
                    b1, b2, b3, b4 = st.columns(4)
                    if b1.button("✅ Validar", key=f"v_{a['id']}"):
                        marcar(caso, a["id"], "validado")
                        st.rerun()
                    if b2.button("❌ Rejeitar", key=f"r_{a['id']}"):
                        marcar(caso, a["id"], "rejeitado")
                        st.rerun()
                    if a["revisao"]["status"] != "pendente" and b3.button("↩ Voltar a pendente", key=f"p_{a['id']}"):
                        marcar(caso, a["id"], "pendente")
                        st.rerun()
                    with b4:
                        botao_abrir(caso, a["caminho"], a["pagina"], f"ab_{a['id']}")

    with sub[2]:
        incluir = st.toggle("Incluir pendentes (prévia)", key="dp_pend",
                            help="Por padrão, só entra o que você validou.")
        dp = dramatis_personae(achados, incluir_pendentes=incluir)
        if not dp["pessoas"] and not dp["empresas"]:
            st.info("Nada validado ainda.")
        for rotulo, itens, campos in (("Pessoas", dp["pessoas"], ("cargos", "empresas")),
                                      ("Empresas", dp["empresas"], ("cnpjs",))):
            if not itens:
                continue
            st.subheader(rotulo)
            st.dataframe(pd.DataFrame([{"Nome": i["nome"], **{c.capitalize(): ", ".join(i[c]) for c in campos},
                                        "Grafias": ", ".join(i["grafias"]), "Documentos": "; ".join(i["documentos"])}
                                       for i in itens]), hide_index=True, use_container_width=True)
            with st.expander(f"Trechos de cada {rotulo.lower()[:-1]}"):
                for i in itens:
                    st.markdown(f"**{html.escape(i['nome'])}**")
                    for f in i["fontes"]:
                        st.markdown(f"<div style='margin-left:1em'>{html.escape(f['localizador'])}: "
                                    f"«{html.escape(' '.join(f['trecho'].split()))}»</div>", unsafe_allow_html=True)

    with sub[3]:
        incluir_lt = st.toggle("Incluir pendentes (prévia)", key="lt_pend")
        lt = linha_do_tempo(achados, incluir_pendentes=incluir_lt)
        if not lt:
            st.info("Nenhum evento validado ainda.")
        for e in lt:
            with st.container(border=True):
                st.markdown(f"**{e['data'] or 'sem data'}** · {html.escape(e['categoria'])}")
                if e["descricao_ia"]:
                    st.caption(f"Resumo da IA: {e['descricao_ia']}")
                st.markdown(f"«{html.escape(' '.join(e['trecho'].split()))}» "
                            f"<span style='color:gray'>— {html.escape(e['localizador'])}</span>", unsafe_allow_html=True)

# ------------------------------------------------------------------ 7. relatório e custódia

with abas[6]:
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
