"""Extração de PDF página a página: texto digital quando a página o tem de fato, OCR quando não.

A decisão é POR PÁGINA (nunca por arquivo) e desconfia do texto digital curto: o SEI carimba
texto («Documento assinado eletronicamente por…») sobre páginas escaneadas. Uma página assim
tem texto digital, mas o conteúdo está na imagem. Pular o OCR deixa a página invisível à busca,
e «não há elemento» vira arquivamento indevido (lição da skill sg-nt:instrucao).
"""

import hashlib
from pathlib import Path

from .texto import limpar_quebras


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


def extrair_pdf(caminho: Path, parametros: dict, dir_caixas: Path | None = None) -> dict:
    import pypdfium2 as pdfium

    from .ocr import ocr_imagem

    dpi = parametros["dpi"]
    idioma = parametros["idioma"]

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
                    imagem = pagina.render(scale=dpi / 72).to_pil()
                    texto, confianca, palavras, tsv = ocr_imagem(imagem, idioma)
                    imagem.close()
                    registro.update(metodo="ocr", motivo_ocr=motivo, texto=limpar_quebras(texto),
                                    confianca_media=confianca, palavras_ocr=palavras)
                    if digital:
                        registro["texto_digital_residual"] = digital
                    if dir_caixas is not None:
                        dir_caixas.mkdir(parents=True, exist_ok=True)
                        arq = dir_caixas / f"p{n:04d}.tsv"
                        arq.write_text(tsv, encoding="utf-8")
                        registro["caixas"] = {"arquivo": arq.name,
                                              "sha256": hashlib.sha256(tsv.encode("utf-8")).hexdigest()}
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
