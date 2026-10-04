"""Processamento de um caso: hash, extração (com OCR) em paralelo, manifesto, índice e triagem.

Retomável: documentos já extraídos com a mesma versão e os mesmos parâmetros são pulados.
Pensado para rodar como processo separado (python -m forense processar <caso>), de modo que
fechar o navegador não interrompe o trabalho.
"""

import importlib.metadata
import multiprocessing
import os
import shutil
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime
from pathlib import Path

from . import EXTRATOR_VERSAO
from .caso import EXTENSOES, Caso, agora, escrever_json_atomico, ler_json
from .ocr import configurar_processo, sha256_arquivo
from .regex_br import entidades_por_pagina
from .sei import identificar as identificar_sei

PARAMETROS_PADRAO = {
    "dpi": 300,
    "idioma": "por",
    # Página com menos que isso de texto digital vai ao OCR (o mesmo limiar da sg-nt:instrucao).
    "limiar_texto_digital": 200,
    # Imagem cobrindo a página e pouco texto digital: é escaneado com carimbo do SEI por cima.
    "cobertura_imagem_ocr": 0.5,
    "texto_digital_max_com_imagem": 1500,
    "forcar_ocr": False,
    "confianca_baixa": 70,  # páginas de OCR abaixo disso geram alerta de conferência visual
}

HEARTBEAT_S = 5
HEARTBEAT_EXPIRA_S = 30


def versoes_bibliotecas() -> dict:
    saida = {}
    for pacote in ("pypdfium2", "pytesseract", "beautifulsoup4", "pillow"):
        try:
            saida[pacote] = importlib.metadata.version(pacote)
        except importlib.metadata.PackageNotFoundError:
            saida[pacote] = None
    return saida


def ferramentas_disponiveis(idioma: str) -> dict:
    try:
        ferramentas = configurar_processo(idioma)
    except RuntimeError as e:
        ferramentas = {"tesseract": None, "erro": str(e)}
    ferramentas["bibliotecas"] = versoes_bibliotecas()
    return ferramentas


def sei_do_documento(doc: dict) -> dict | None:
    """Identificação SEI pelo caminho (dentro de originais/) e pelo cabeçalho das primeiras páginas.
    Barata e sem OCR: recalculada nos documentos já extraídos quando a regra muda."""
    rel = doc["arquivo"]["caminhos"][0]
    rel = rel.split("/", 1)[1] if rel.startswith("originais/") else rel
    inicio = "\n".join(pg.get("texto") or "" for pg in doc["paginas"][:2])
    return identificar_sei(rel, "." + rel.rsplit(".", 1)[-1].lower(), inicio)


# ------------------------------------------------------------------ worker (outro processo)

_FERRAMENTAS_WORKER: dict = {}


def _inicializar_worker(idioma: str) -> None:
    global _FERRAMENTAS_WORKER
    _FERRAMENTAS_WORKER = ferramentas_disponiveis(idioma)


def _novo_documento(p: Path, sha256: str, caminhos_rel: list[str], parametros: dict) -> dict:
    return {
        "schema": "doc-forense/documento@1",
        "documento_id": sha256[:16],
        "arquivo": {
            "nome": p.name,
            "caminhos": caminhos_rel,
            "tipo": EXTENSOES[p.suffix.lower()],
            "tamanho_bytes": p.stat().st_size,
            "sha256": sha256,
            "modificado_em_sistema": datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
        },
        "extracao": {
            "extraido_em": agora(),
            "extrator_versao": EXTRATOR_VERSAO,
            "parametros": parametros,
            "ferramentas": _FERRAMENTAS_WORKER,
        },
        "status": "ok",
        "erros": [],
        "alertas": [],
        "paginas": [],
    }


def _registrar_erro(doc: dict, e: Exception) -> None:
    doc["status"] = "erro"
    doc["erros"].append(f"{type(e).__name__}: {e}")
    doc["erros"].append(traceback.format_exc(limit=3))


def finalizar_documento(doc: dict, parametros: dict, destino: str, duracao_s: float) -> dict:
    """Entidades, SEI, alertas e status; grava o JSON da camada bruta e devolve o resumo."""
    if doc["status"] != "erro":
        try:
            doc["entidades"] = entidades_por_pagina(doc["paginas"])
            doc["sei"] = sei_do_documento(doc)
        except Exception as e:
            _registrar_erro(doc, e)
    for pg in doc["paginas"]:
        if pg["metodo"] == "ocr":
            conf = pg.get("confianca_media")
            if conf is not None and conf < parametros["confianca_baixa"]:
                pg["confianca_baixa"] = True
                doc["alertas"].append(f"Página {pg['n']}: OCR com confiança {conf:.0f}% — conferir com a imagem original.")
            if pg["caracteres"] < 20:
                doc["alertas"].append(f"Página {pg['n']}: quase sem texto após OCR (imagem, página em branco ou manuscrito?).")
            if pg.get("dpi_efetivo"):
                doc["alertas"].append(f"Página {pg['n']}: página muito grande; OCR feito a {pg['dpi_efetivo']} dpi.")
        elif pg["metodo"] == "erro":
            doc["alertas"].append(f"Página {pg['n']}: falha na extração.")
    if doc["status"] == "ok" and any(pg["metodo"] == "erro" for pg in doc["paginas"]):
        doc["status"] = "parcial"
    if doc["status"] == "ok" and not any(pg["caracteres"] for pg in doc["paginas"]):
        doc["status"] = "parcial"
        doc["alertas"].append("Nenhum texto extraído do documento.")
    doc["extracao"]["duracao_s"] = round(duracao_s, 2)
    escrever_json_atomico(Path(destino), doc)
    return {
        "arquivo": doc["arquivo"]["nome"], "sha256": doc["arquivo"]["sha256"], "status": doc["status"],
        "paginas": len(doc["paginas"]),
        "paginas_ocr": sum(1 for pg in doc["paginas"] if pg["metodo"] == "ocr"),
        "duracao_s": doc["extracao"]["duracao_s"],
    }


def processar_documento(caminho: str, sha256: str, caminhos_rel: list[str], parametros: dict, destino: str) -> dict:
    """Extrai um documento inteiro num processo e grava o JSON. Nunca levanta exceção."""
    from .extrator_html import extrair_html
    from .extrator_pdf import extrair_pdf

    inicio = time.monotonic()
    p = Path(caminho)
    doc = _novo_documento(p, sha256, caminhos_rel, parametros)
    try:
        if sha256_arquivo(p) != sha256:
            raise RuntimeError("o arquivo mudou durante o processamento (hash diferente)")
        if doc["arquivo"]["tipo"] == "html":
            resultado = extrair_html(p, parametros)
        else:
            dir_caixas = Path(destino).parent / "caixas" / sha256[:16]
            shutil.rmtree(dir_caixas, ignore_errors=True)  # reextração: caixas antigas saem
            resultado = extrair_pdf(p, parametros, dir_caixas=dir_caixas)
        doc["paginas"] = resultado.pop("paginas")
        doc["erros"] = resultado.pop("erros")
        doc.update(resultado)
    except Exception as e:
        _registrar_erro(doc, e)
    return finalizar_documento(doc, parametros, destino, time.monotonic() - inicio)


def preparar_pdf(caminho: str, sha256: str, caminhos_rel: list[str], parametros: dict, destino: str) -> dict:
    """Primeira etapa de um PDF: texto digital e plano de OCR. Devolve o documento parcial."""
    from .extrator_pdf import planejar_pdf

    p = Path(caminho)
    doc = _novo_documento(p, sha256, caminhos_rel, parametros)
    try:
        if sha256_arquivo(p) != sha256:
            raise RuntimeError("o arquivo mudou durante o processamento (hash diferente)")
        shutil.rmtree(Path(destino).parent / "caixas" / sha256[:16], ignore_errors=True)
        plano = planejar_pdf(p, parametros)
        doc["paginas"] = plano.pop("paginas")
        doc["erros"] = plano.pop("erros")
        doc.update(plano)
    except Exception as e:
        _registrar_erro(doc, e)
    return doc


def ocr_lote(caminho: str, registros: list[dict], parametros: dict, dir_caixas: str) -> list[dict]:
    """Segunda etapa: OCR de um lote de páginas de um PDF."""
    from .extrator_pdf import ocr_paginas_pdf

    return ocr_paginas_pdf(Path(caminho), registros, parametros, Path(dir_caixas))


# ------------------------------------------------------------------ progresso

class Progresso:
    """Arquivo progresso.json com heartbeat, lido pela interface para saber se há execução ativa."""

    def __init__(self, caso: Caso):
        self.caso = caso
        self.dados = {"estado": "executando", "inicio": agora(), "etapa": "preparando",
                      "total": 0, "concluidos": 0, "atual": None, "erros": 0}
        self._trava = threading.Lock()
        self._parar = threading.Event()
        self._thread = threading.Thread(target=self._bater, daemon=True)

    def __enter__(self):
        self.salvar()
        self._thread.start()
        return self

    def __exit__(self, tipo, valor, tb):
        self._parar.set()
        self._thread.join(timeout=HEARTBEAT_S + 1)
        if tipo is not None:
            self.atualizar(estado="falhou", mensagem=f"{tipo.__name__}: {valor}")
        elif self.dados["estado"] == "executando":
            self.atualizar(estado="concluido")

    def _bater(self):
        while not self._parar.wait(HEARTBEAT_S):
            self.salvar()

    def atualizar(self, **campos):
        with self._trava:
            self.dados.update(campos)
        self.salvar()

    def salvar(self):
        """O progresso é só informativo: falhar ao gravá-lo nunca interrompe o processamento."""
        with self._trava:
            self.dados["heartbeat"] = time.time()
            try:
                escrever_json_atomico(self.caso.progresso, self.dados)
            except OSError:
                pass  # a próxima batida (5 s) tenta de novo


def ler_progresso(caso: Caso) -> dict | None:
    if not caso.progresso.exists():
        return None
    try:
        dados = ler_json(caso.progresso)
    except (OSError, ValueError):
        return None
    if dados.get("estado") == "executando" and time.time() - dados.get("heartbeat", 0) > HEARTBEAT_EXPIRA_S:
        dados["estado"] = "interrompido"
    return dados


def em_execucao(caso: Caso) -> bool:
    p = ler_progresso(caso)
    return bool(p and p["estado"] == "executando")


# ------------------------------------------------------------------ orquestração

def _ja_extraido(caminho_json: Path, parametros: dict) -> dict | None:
    if not caminho_json.exists():
        return None
    try:
        doc = ler_json(caminho_json)
    except (OSError, ValueError):
        return None
    ext = doc.get("extracao", {})
    if ext.get("extrator_versao") != EXTRATOR_VERSAO or ext.get("parametros") != parametros:
        return None
    if doc.get("status") == "erro":
        return None  # tenta de novo
    return doc


LOTE_PAGINAS_OCR = 4  # páginas por tarefa de OCR: pequeno o bastante para repartir, grande o bastante para amortizar a abertura do PDF


def _executar_extracao(caso: Caso, pendentes: list, parametros: dict, workers: int, resumo: dict, prog, log) -> None:
    # spawn em todas as plataformas: é o modo do Windows e evita fork com thread ativa
    contexto = multiprocessing.get_context("spawn")
    feitos = 0

    def concluir(r: dict, origem: str | None = None, erro: str | None = None):
        nonlocal feitos
        if erro:
            caso.registrar("falha_worker", arquivo=origem, erro=erro)
        feitos += 1
        resumo["processados"] += 1
        resumo["paginas_ocr"] += r["paginas_ocr"]
        if r["status"] == "erro":
            resumo["erros"] += 1
        elif r["status"] == "parcial":
            resumo["parciais"] += 1
        log(f"  [{feitos}/{len(pendentes)}] {r['arquivo']}: {r['status']}, {r['paginas']} pág. "
            f"({r['paginas_ocr']} OCR), {r['duracao_s']}s")
        prog.atualizar(concluidos=feitos, atual=r["arquivo"], erros=resumo["erros"])

    def falha(args) -> dict:
        return {"arquivo": Path(args[0]).name, "status": "erro", "paginas": 0, "paginas_ocr": 0, "duracao_s": 0}

    with ProcessPoolExecutor(max_workers=workers, mp_context=contexto,
                             initializer=_inicializar_worker, initargs=(parametros["idioma"],)) as pool:
        ativos: dict = {}
        estado: dict = {}  # destino -> {"doc", "args", "inicio", "faltam", "total_ocr", "feitas"}
        for args in pendentes:
            tarefa = processar_documento if Path(args[0]).suffix.lower() in (".html", ".htm") else preparar_pdf
            ativos[pool.submit(tarefa, *args)] = (tarefa.__name__, args)
            estado[args[4]] = {"inicio": time.monotonic(), "args": args}

        while ativos:
            prontos, _ = wait(ativos, return_when=FIRST_COMPLETED)
            for fut in prontos:
                tipo, args = ativos.pop(fut)
                destino = args[4]
                st = estado[destino]
                try:
                    resultado = fut.result()
                except Exception as e:  # falha do processo em si (ex.: memória esgotada)
                    if st.get("abortado"):
                        continue
                    st["abortado"] = True
                    concluir(falha(args), args[0], str(e))
                    continue
                if st.get("abortado"):
                    continue

                if tipo == "processar_documento":
                    concluir(resultado)
                elif tipo == "preparar_pdf":
                    doc = resultado
                    pendentes_ocr = [pg for pg in doc["paginas"] if pg["metodo"] == "pendente_ocr"]
                    st.update(doc=doc, faltam=0, total_ocr=len(pendentes_ocr), feitas=0)
                    dir_caixas = str(Path(destino).parent / "caixas" / args[1][:16])
                    for k in range(0, len(pendentes_ocr), LOTE_PAGINAS_OCR):
                        lote = pendentes_ocr[k:k + LOTE_PAGINAS_OCR]
                        ativos[pool.submit(ocr_lote, args[0], lote, parametros, dir_caixas)] = ("ocr_lote", args)
                        st["faltam"] += 1
                    if not st["faltam"]:
                        concluir(finalizar_documento(doc, parametros, destino, time.monotonic() - st["inicio"]))
                else:  # ocr_lote
                    feitas = {pg["n"]: pg for pg in resultado}
                    doc = st["doc"]
                    doc["paginas"] = [feitas.get(pg["n"], pg) for pg in doc["paginas"]]
                    doc["erros"] += [f"página {pg['n']}: {pg['erro']}" for pg in resultado if pg["metodo"] == "erro"]
                    st["faltam"] -= 1
                    st["feitas"] += len(resultado)
                    if st["total_ocr"] > LOTE_PAGINAS_OCR:
                        prog.atualizar(atual=f"{doc['arquivo']['nome']}: OCR {st['feitas']}/{st['total_ocr']} páginas")
                    if not st["faltam"]:
                        concluir(finalizar_documento(doc, parametros, destino, time.monotonic() - st["inicio"]))


def processar_caso(caso: Caso, parametros: dict | None = None, workers: int | None = None, log=print) -> dict:
    from .indice import reconstruir_indice
    from .triagem import triar_caso

    parametros = {**PARAMETROS_PADRAO, **(parametros or {})}
    workers = workers or max(1, (os.cpu_count() or 2) // 2)

    if em_execucao(caso):
        raise RuntimeError("Já existe um processamento em andamento para este caso.")

    with Progresso(caso) as prog:
        caso.registrar("processamento_iniciado", parametros=parametros, workers=workers)
        ferramentas = ferramentas_disponiveis(parametros["idioma"])
        if not ferramentas.get("tesseract"):
            log(f"[!] {ferramentas.get('erro')} PDFs escaneados ficarão sem texto.")

        # 1) hash de todos os originais (agrupa duplicatas)
        suportados, ignorados = caso.listar_originais()
        prog.atualizar(etapa="calculando hashes", total=len(suportados))
        por_hash: dict[str, list[Path]] = {}
        for i, p in enumerate(suportados, 1):
            por_hash.setdefault(sha256_arquivo(p), []).append(p)
            prog.atualizar(concluidos=i, atual=p.name)
        log(f"[*] {len(suportados)} arquivos ({len(por_hash)} distintos), {len(ignorados)} ignorados (formato não suportado).")

        # 2) separa pendentes e já extraídos
        pendentes = []
        for sha, caminhos in por_hash.items():
            rels = [caso.relativo(c) for c in caminhos]
            destino = caso.caminho_json(sha)
            existente = _ja_extraido(destino, parametros)
            if existente is None:
                pendentes.append((str(caminhos[0]), sha, rels, parametros, str(destino)))
            else:
                mudou = []
                if existente["arquivo"]["caminhos"] != rels:
                    existente["arquivo"]["caminhos"] = rels
                    mudou.append("caminhos")
                sei = sei_do_documento(existente)
                if existente.get("sei") != sei:
                    existente["sei"] = sei
                    mudou.append("sei")
                if mudou:  # metadados recalculados; o texto e o OCR ficam como estão
                    escrever_json_atomico(destino, existente)
                    caso.registrar("metadados_atualizados", sha256=sha, campos=mudou,
                                   caminhos=rels, sei=(sei or {}).get("numero"))

        # documentos cujo original saiu da pasta vão para extraido/removidos (não são apagados)
        validos = {caso.caminho_json(sha).name for sha in por_hash}
        for j in caso.extraido.glob("*.json"):
            if j.name not in validos:
                (caso.extraido / "removidos").mkdir(exist_ok=True)
                shutil.move(str(j), caso.extraido / "removidos" / j.name)
                caixas = caso.extraido / "caixas" / j.stem
                if caixas.is_dir():
                    shutil.move(str(caixas), caso.extraido / "removidos" / f"caixas_{j.stem}")
                caso.registrar("extracao_arquivada", json=j.name, motivo="original não está mais na pasta")

        log(f"[*] {len(pendentes)} para extrair, {len(por_hash) - len(pendentes)} já extraídos.")

        # 3) extração em paralelo. HTML vai inteiro a um processo. PDF passa por duas etapas: o plano
        # (texto digital e decisão de OCR) e o OCR em lotes de páginas, distribuídos entre os
        # processos à medida que ficam livres. Assim um PDF de 1.000 páginas não ocupa um núcleo
        # só enquanto os outros esperam.
        prog.atualizar(etapa="extraindo texto", total=len(pendentes), concluidos=0, atual=None)
        resumo = {"processados": 0, "erros": 0, "parciais": 0, "paginas_ocr": 0}
        if pendentes:
            _executar_extracao(caso, pendentes, parametros, workers, resumo, prog, log)

        # 4) manifesto, índice e triagem
        prog.atualizar(etapa="gerando manifesto", atual=None)
        caso.gerar_manifesto(ferramentas, parametros)
        prog.atualizar(etapa="indexando")
        reconstruir_indice(caso)
        prog.atualizar(etapa="triagem")
        triar_caso(caso)

        caso.registrar("processamento_concluido", **resumo)
        prog.atualizar(etapa="concluído", resumo=resumo)
        log(f"[✓] Concluído: {resumo}")
        return resumo
