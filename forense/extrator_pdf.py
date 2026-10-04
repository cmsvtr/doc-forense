"""Extração de PDF página a página: texto digital quando a página o tem de fato, OCR quando não.

A decisão é POR PÁGINA (nunca por arquivo) e desconfia do texto digital curto: o SEI carimba
texto («Documento assinado eletronicamente por…») sobre páginas escaneadas. Uma página assim
tem texto digital, mas o conteúdo está na imagem. Pular o OCR deixa a página invisível à busca,
e «não há elemento» vira arquivamento indevido (lição da skill sg-nt:instrucao).

Duas etapas, para o OCR de um PDF grande poder ser dividido entre os núcleos:
  planejar_pdf      lê o texto digital e decide quais páginas vão ao OCR (rápido)
  ocr_paginas_pdf   faz o OCR de um lote de páginas (lento; vários lotes em paralelo)
"""

import hashlib
from pathlib import Path

from .texto import limpar_quebras

# Lado maior da imagem enviada ao OCR. A 300 dpi, A4 tem 3.508 px e A2 tem 7.016 px. Página
# maior (planta, mapa, foto escaneada sem redução) é renderizada com resolução menor: a 300 dpi,
# um A0 viraria uma imagem de 140 megapixels, lenta e capaz de esgotar a memória com vários
# processos ao mesmo tempo.
MAX_LADO_PX = 7000


def _cobertura_imagem(pagina) -> float:
    """Fração (0-1) da área da página coberta por imagens (soma das caixas, limitada a 1)."""
    import pypdfium2.raw as pdfium_c

    largura, altura = pagina.get_size()
    area = max(largura * altura, 1.0)
    coberta = 0.0
    for obj in pagina.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=3):
        esq, base, dir_, topo = obj.get_bounds()
        w = max(0.0, min(dir_, largura) - max(esq, 0.0))
        h = max(0.0, min(topo, altura) - max(base, 0.0))
        coberta += w * h
    return min(coberta / area, 1.0)


def decidir_ocr(texto_digital: str, cobertura_imagem: float, parametros: dict) -> str | None:
    """Motivo para fazer OCR, ou None se o texto digital basta."""
    if parametros.get("forcar_ocr"):
        return "OCR forçado"
    util = len(texto_digital.strip())
    if util < parametros["limiar_texto_digital"]:
        return f"pouco texto digital ({util} caracteres)"
    if cobertura_imagem >= parametros["cobertura_imagem_ocr"] and util < parametros["texto_digital_max_com_imagem"]:
        return f"imagem cobre {cobertura_imagem:.0%} da página"
    return None


def escala_de_renderizacao(largura_pt: float, altura_pt: float, dpi: int) -> tuple[float, int]:
    """(escala para o pdfium, dpi efetivo), respeitando MAX_LADO_PX."""
    escala = dpi / 72
    lado = max(largura_pt, altura_pt) * escala
    if lado > MAX_LADO_PX:
        escala = MAX_LADO_PX / max(largura_pt, altura_pt)
    return escala, round(escala * 72)


def planejar_pdf(caminho: Path, parametros: dict) -> dict:
    """Texto digital de cada página e a decisão de OCR. As páginas que vão ao OCR saem com
    metodo «pendente_ocr», para ocr_paginas_pdf completar."""
    import pypdfium2 as pdfium

    paginas: list[dict] = []
    erros: list[str] = []
    metadados: dict = {}
    pdf = pdfium.PdfDocument(str(caminho))
    try:
        try:
            metadados = dict(pdf.get_metadata_dict(skip_empty=True))
        except Exception as e:  # metadados são acessórios; não interrompem a extração
            erros.append(f"metadados ilegíveis: {e}")
        for i in range(len(pdf)):
            n = i + 1
            pagina = pdf[i]
            registro: dict = {"n": n}
            try:
                tp = pagina.get_textpage()
                digital = limpar_quebras(tp.get_text_range() or "")
                tp.close()
                cobertura = _cobertura_imagem(pagina)
                motivo = decidir_ocr(digital, cobertura, parametros)
                if motivo is None:
                    registro.update(metodo="texto_digital", texto=digital)
                else:
                    registro.update(metodo="pendente_ocr", motivo_ocr=motivo, texto="")
                    if digital:
                        registro["texto_digital_residual"] = digital
                if cobertura:
                    registro["cobertura_imagem"] = round(cobertura, 2)
            except Exception as e:
                registro.update(metodo="erro", texto="", erro=f"{type(e).__name__}: {e}")
                erros.append(f"página {n}: {type(e).__name__}: {e}")
            finally:
                pagina.close()
            registro["caracteres"] = len(registro.get("texto", ""))
            paginas.append(registro)
    finally:
        pdf.close()
    return {"paginas": paginas, "erros": erros, "metadados_pdf": metadados}


def ocr_paginas_pdf(caminho: Path, registros: list[dict], parametros: dict,
                    dir_caixas: Path | None = None) -> list[dict]:
    """OCR das páginas «pendente_ocr» recebidas; devolve os registros completos. Erro numa página
    vira registro de erro, sem interromper as outras."""
    import pypdfium2 as pdfium

    from .ocr import ocr_imagem

    saida = []
    pdf = pdfium.PdfDocument(str(caminho))
    try:
        for reg in registros:
            reg = dict(reg)
            pagina = pdf[reg["n"] - 1]
            try:
                escala, dpi_efetivo = escala_de_renderizacao(*pagina.get_size(), parametros["dpi"])
                imagem = pagina.render(scale=escala, grayscale=True).to_pil()
                texto, confianca, palavras, tsv = ocr_imagem(imagem, parametros["idioma"])
                imagem.close()
                reg.update(metodo="ocr", texto=limpar_quebras(texto), confianca_media=confianca, palavras_ocr=palavras)
                if dpi_efetivo < parametros["dpi"]:
                    reg["dpi_efetivo"] = dpi_efetivo
                if dir_caixas is not None:
                    dir_caixas.mkdir(parents=True, exist_ok=True)
                    arq = dir_caixas / f"p{reg['n']:04d}.tsv"
                    arq.write_text(tsv, encoding="utf-8")
                    reg["caixas"] = {"arquivo": arq.name, "sha256": hashlib.sha256(tsv.encode("utf-8")).hexdigest()}
            except Exception as e:
                reg.update(metodo="erro", texto="", erro=f"{type(e).__name__}: {e}")
            finally:
                pagina.close()
            reg["caracteres"] = len(reg.get("texto", ""))
            saida.append(reg)
    finally:
        pdf.close()
    return saida


def extrair_pdf(caminho: Path, parametros: dict, dir_caixas: Path | None = None) -> dict:
    """As duas etapas em sequência, num processo só."""
    plano = planejar_pdf(caminho, parametros)
    pendentes = [p for p in plano["paginas"] if p["metodo"] == "pendente_ocr"]
    if pendentes:
        feitas = {p["n"]: p for p in ocr_paginas_pdf(caminho, pendentes, parametros, dir_caixas)}
        plano["paginas"] = [feitas.get(p["n"], p) for p in plano["paginas"]]
        plano["erros"] += [f"página {p['n']}: {p['erro']}" for p in feitas.values() if p["metodo"] == "erro"]
    return plano
