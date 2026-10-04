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
from concurrent.futures import ProcessPoolExecutor, as_completed
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


# ------------------------------------------------------------------ worker (outro processo)

_FERRAMENTAS_WORKER: dict = {}


def _inicializar_worker(idioma: str) -> None:
    global _FERRAMENTAS_WORKER
    _FERRAMENTAS_WORKER = ferramentas_disponiveis(idioma)


def processar_documento(caminho: str, sha256: str, caminhos_rel: list[str], parametros: dict, destino: str) -> dict:
    """Extrai um documento e grava o JSON da camada bruta. Nunca levanta exceção."""
    from .extrator_html import extrair_html
    from .extrator_pdf import extrair_pdf

    inicio = time.monotonic()
    p = Path(caminho)
    tipo = EXTENSOES[p.suffix.lower()]
    doc = {
        "schema": "doc-forense/documento@1",
        "documento_id": sha256[:16],
        "arquivo": {
            "nome": p.name,
            "caminhos": caminhos_rel,
            "tipo": tipo,
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
    try:
        if sha256_arquivo(p) != sha256:
            raise RuntimeError("o arquivo mudou durante o processamento (hash diferente)")
        if tipo == "html":
            resultado = extrair_html(p, parametros)
        else:
            dir_caixas = Path(destino).parent / "caixas" / sha256[:16]
            shutil.rmtree(dir_caixas, ignore_errors=True)  # reextração: caixas antigas saem
            resultado = extrair_pdf(p, parametros, dir_caixas=dir_caixas)
        doc["paginas"] = resultado.pop("paginas")
        doc["erros"] = resultado.pop("erros")
        doc.update(resultado)
        doc["entidades"] = entidades_por_pagina(doc["paginas"])
        inicio_texto = "\n".join(pg.get("texto", "") for pg in doc["paginas"][:2])
        rel_originais = caminhos_rel[0].split("/", 1)[1] if "/" in caminhos_rel[0] else caminhos_rel[0]
        doc["sei"] = identificar_sei(rel_originais, p.suffix.lower(), inicio_texto)
    except Exception as e:
        doc["status"] = "erro"
        doc["erros"].append(f"{type(e).__name__}: {e}")
        doc["erros"].append(traceback.format_exc(limit=3))

    for pg in doc["paginas"]:
        if pg["metodo"] == "ocr":
            conf = pg.get("confianca_media")
            if conf is not None and conf < parametros["confianca_baixa"]:
                pg["confianca_baixa"] = True
                doc["alertas"].append(f"Página {pg['n']}: OCR com confiança {conf:.0f}% — conferir com a imagem original.")
            if pg["caracteres"] < 20:
                doc["alertas"].append(f"Página {pg['n']}: quase sem texto após OCR (imagem, página em branco ou manuscrito?).")
        elif pg["metodo"] == "erro":
            doc["alertas"].append(f"Página {pg['n']}: falha na extração.")
    if doc["status"] == "ok" and any(pg["metodo"] == "erro" for pg in doc["paginas"]):
        doc["status"] = "parcial"
    if doc["status"] == "ok" and not any(pg["caracteres"] for pg in doc["paginas"]):
        doc["status"] = "parcial"
        doc["alertas"].append("Nenhum texto extraído do documento.")

    doc["extracao"]["duracao_s"] = round(time.monotonic() - inicio, 2)
    escrever_json_atomico(Path(destino), doc)
    return {
        "arquivo": p.name, "sha256": sha256, "status": doc["status"],
        "paginas": len(doc["paginas"]),
        "paginas_ocr": sum(1 for pg in doc["paginas"] if pg["metodo"] == "ocr"),
        "duracao_s": doc["extracao"]["duracao_s"],
    }


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
            elif existente["arquivo"]["caminhos"] != rels:
                existente["arquivo"]["caminhos"] = rels
                escrever_json_atomico(destino, existente)
                caso.registrar("caminhos_atualizados", sha256=sha, caminhos=rels)

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

        # 3) extração em paralelo
        prog.atualizar(etapa="extraindo texto", total=len(pendentes), concluidos=0, atual=None)
        resumo = {"processados": 0, "erros": 0, "parciais": 0, "paginas_ocr": 0}
        if pendentes:
            # spawn em todas as plataformas: é o modo do Windows e evita fork com thread ativa
            with ProcessPoolExecutor(max_workers=min(workers, len(pendentes)),
                                     mp_context=multiprocessing.get_context("spawn"),
                                     initializer=_inicializar_worker,
                                     initargs=(parametros["idioma"],)) as pool:
                futuros = {pool.submit(processar_documento, *args): args for args in pendentes}
                for i, fut in enumerate(as_completed(futuros), 1):
                    args = futuros[fut]
                    try:
                        r = fut.result()
                    except Exception as e:  # falha do processo em si (ex.: memória)
                        r = {"arquivo": Path(args[0]).name, "status": "erro", "paginas": 0, "paginas_ocr": 0, "duracao_s": 0}
                        caso.registrar("falha_worker", arquivo=args[0], erro=str(e))
                    resumo["processados"] += 1
                    resumo["paginas_ocr"] += r["paginas_ocr"]
                    if r["status"] == "erro":
                        resumo["erros"] += 1
                    elif r["status"] == "parcial":
                        resumo["parciais"] += 1
                    log(f"  [{i}/{len(pendentes)}] {r['arquivo']}: {r['status']}, {r['paginas']} pág. "
                        f"({r['paginas_ocr']} OCR), {r['duracao_s']}s")
                    prog.atualizar(concluidos=i, atual=r["arquivo"], erros=resumo["erros"])

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
