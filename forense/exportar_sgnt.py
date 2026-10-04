"""Exporta a camada bruta no formato de corpus da skill sg-nt:instrucao (Fase 3).

O OCR é a etapa cara (horas) e não se paga duas vezes. Feito aqui, localmente e em segundo plano,
ele é reaproveitado pela skill, que no Cowork não consegue rodar processos longos:

    exportacao_sgnt/corpus/
        _caixas/<arquivo>/pNNNN.tsv   caixas de palavra do Tesseract (mesmo formato da skill)
        _caixas/<arquivo>/pNNNN.txt   texto da página OCR, como a skill o remonta
        <SEI>.txt                     texto do documento, páginas separadas por \\f
        _cobertura.tsv                páginas com texto, com OCR e invisíveis, por arquivo
        _ocr_duvidoso.tsv             páginas de OCR com confiança < 70 ou menos de 20 palavras
        LEIA-ME.txt

Na skill: copie a pasta _caixas para instrucao/corpus/ e rode o build_corpus.py com --sem-ocr.
"""

import re
import shutil
from pathlib import PurePosixPath

from .caso import Caso, agora

CONF_MIN = 70
PALAVRAS_MIN = 20


def texto_do_tsv_sgnt(tsv: str) -> str:
    """Mesma reconstrução do build_corpus.py (uma linha por linha do Tesseract, sem linha em branco)."""
    linhas, atual, chave_ant = [], [], None
    for l in tsv.split("\n")[1:]:
        c = l.split("\t")
        if len(c) < 12:
            continue
        palavra = c[11].strip()
        if not palavra or palavra == "-1":
            continue
        chave = (c[1], c[2], c[3], c[4])
        if chave != chave_ant and atual:
            linhas.append(" ".join(atual))
            atual = []
        chave_ant = chave
        atual.append(palavra)
    if atual:
        linhas.append(" ".join(atual))
    return "\n".join(linhas)


def _alvos(doc: dict) -> list[str]:
    """Nomes dos .txt do corpus para o documento, pela regra da skill (SEI do nome, do cabeçalho
    ou da pasta de anexo); sem SEI, o nome do arquivo."""
    sei = doc.get("sei") or {}
    alvos = set()
    if sei.get("fonte") == "pasta de anexo":
        rel = re.sub(r"[\\/]+", " - ", str(PurePosixPath(sei["anexo"]).with_suffix("")))
        alvos.add(f"{sei['numero']}/{rel}")
    elif sei.get("numero"):
        alvos.add(sei["numero"])
    if sei.get("numero_no_cabecalho"):
        alvos.add(sei["numero_no_cabecalho"])
    return sorted(alvos) or [PurePosixPath(doc["arquivo"]["caminhos"][0]).stem]


def exportar(caso: Caso) -> dict:
    saida = caso.raiz / "exportacao_sgnt" / "corpus"
    if saida.exists():
        shutil.rmtree(saida)
    (saida / "_caixas").mkdir(parents=True)

    por_alvo: dict[str, list[str]] = {}
    cobertura, duvidosas = [], []
    caixas_exportadas = 0
    for doc in caso.documentos():
        nome = doc["arquivo"]["nome"]
        base = PurePosixPath(doc["arquivo"]["caminhos"][0]).stem
        origem_caixas = caso.extraido / "caixas" / doc["documento_id"]
        com_texto = ocr = invisiveis = 0
        for pg in doc["paginas"]:
            if pg["metodo"] in ("texto_digital", "html", "texto"):
                com_texto += 1
            elif pg["metodo"] == "ocr" and pg.get("caracteres"):
                ocr += 1
            else:
                invisiveis += 1
            cx = pg.get("caixas")
            if cx and (origem_caixas / cx["arquivo"]).exists():
                destino = saida / "_caixas" / base
                destino.mkdir(exist_ok=True)
                tsv = (origem_caixas / cx["arquivo"]).read_text(encoding="utf-8")
                (destino / f"p{pg['n']:04d}.tsv").write_text(tsv, encoding="utf-8")
                (destino / f"p{pg['n']:04d}.txt").write_text(texto_do_tsv_sgnt(tsv), encoding="utf-8")
                caixas_exportadas += 1
                conf, npal = pg.get("confianca_media") or 0.0, pg.get("palavras_ocr", 0)
                if conf < CONF_MIN or npal < PALAVRAS_MIN:
                    duvidosas.append((nome, doc["arquivo"]["caminhos"][0], pg["n"], conf, npal))
        texto = "\f".join(pg.get("texto") or "" for pg in doc["paginas"])
        alvos = _alvos(doc)
        for alvo in alvos:
            por_alvo.setdefault(alvo, []).append(texto)
        total = len(doc["paginas"])
        cobertura.append((nome, ",".join(alvos), total, com_texto, ocr, invisiveis,
                          (com_texto + ocr) / max(1, total)))

    for alvo, textos in por_alvo.items():
        arq = saida / f"{alvo}.txt"
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text("".join(t + "\n" for t in textos), encoding="utf-8")

    with open(saida / "_cobertura.tsv", "w", encoding="utf-8") as f:
        f.write("arquivo\tids\tpaginas\tcom_texto\tocr\tinvisiveis\tcobertura\n")
        for c in sorted(cobertura, key=lambda x: x[6]):
            f.write("%s\t%s\t%d\t%d\t%d\t%d\t%.3f\n" % c)
    if duvidosas:
        with open(saida / "_ocr_duvidoso.tsv", "w", encoding="utf-8") as f:
            f.write("arquivo\tcaminho\tpagina\tconfianca\tpalavras\n")
            for nome, cam, pg, conf, npal in sorted(duvidosas, key=lambda x: x[3]):
                f.write("%s\t%s\t%d\t%.0f\t%d\n" % (nome, cam, pg, conf, npal))

    (saida / "LEIA-ME.txt").write_text(
        f"Corpus exportado pelo doc-forense em {agora()} (caso {caso.nome}).\n\n"
        "Para a skill sg-nt:instrucao (Fase 3), sem refazer o OCR:\n"
        "  1. copie a pasta _caixas para <pasta do caso>/instrucao/corpus/\n"
        "  2. rode: python build_corpus.py <processo> <apartado> --out instrucao/corpus --sem-ocr\n"
        "     (os nomes dos arquivos de autos precisam ser os mesmos usados aqui)\n\n"
        "Os <SEI>.txt já servem ao find_quote.py e à conferência na fonte. O texto das páginas\n"
        "digitais vem do pdfium; o build_corpus.py o refaz com o pdftotext.\n",
        encoding="utf-8")
    resumo = {"documentos": len(cobertura), "arquivos_txt": len(por_alvo),
              "paginas_com_caixas": caixas_exportadas, "paginas_duvidosas": len(duvidosas),
              "pasta": str(saida)}
    caso.registrar("exportacao_sgnt", **{k: v for k, v in resumo.items() if k != "pasta"})
    return resumo
