"""Gera um caso de teste com documentos sintéticos (nenhum dado real)."""

from pathlib import Path

import pytest

from forense.caso import Caso
from forense.ocr import localizar_tessdata, localizar_tesseract

FONTES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

EMAIL_HTML = """<html><head><meta charset="utf-8"><title>RE: Pregão 12/2024</title></head><body>
<p><b>De:</b> Carlos Mendes &lt;carlos.mendes@alfaengenharia.com.br&gt;<br>
<b>Enviado em:</b> quinta-feira, 14 de março de 2024 10:32<br>
<b>Para:</b> Marcos Souza &lt;marcos@betaconstrucoes.com.br&gt;<br>
<b>Assunto:</b> RE: Pregão 12/2024</p>
<p>Marcos, conforme combinado no almoço, vocês entram com proposta de cobertura no lote 2
e nós ficamos com o lote 1. Na próxima licitação é a vez de vocês.</p>
<p>Melhor não tratar disso por e-mail. Me liga pelo celular pessoal. Apague esta mensagem.</p>
<p>Engenharia Alfa S/A — CNPJ 11.222.333/0001-81<br>
Beta Construções Ltda — CNPJ 12.ABC.345/01DE-35</p>
<hr>
<p><b>De:</b> Marcos Souza &lt;marcos@betaconstrucoes.com.br&gt;<br>
<b>Enviado em:</b> 13/03/2024 18:05<br>
<b>Para:</b> Carlos Mendes &lt;carlos.mendes@alfaengenharia.com.br&gt;<br>
<b>Assunto:</b> Pregão 12/2024</p>
<p>Carlos, qual vai ser o seu preço no lote 1? Nossa proposta será R$ 1.250.000,00 no lote 2.</p>
<script>alert('não deve aparecer')</script>
</body></html>"""

NEUTRO_HTML = """<html><head><meta charset="utf-8"><title>Boletim interno</title></head><body>
<h1>Boletim de segurança do trabalho</h1>
<p>Em 02/02/2024 realizamos o treinamento anual de uso de EPI no canteiro de obras.
Todos os colaboradores devem usar capacete e botas.</p></body></html>"""

ATA_TEXTO = [
    "ATA DE REUNIÃO - 10 de maio de 2024",
    "Presentes: diretores comerciais das empresas do grupo.",
    "Ficou acertado manter os preços da tabela única",
    "e a divisão de clientes por região a partir de junho.",
    "Responsável: João da Silva, CPF 529.982.247-25.",
]

ESCANEADO_TEXTO = [
    "TERMO DE ENTENDIMENTO",
    "As empresas não vão participar do certame",
    "do lote 3, em troca de subcontratação.",
    "Proposta de cobertura com valor acima",
    "do orçamento. São Paulo, 20/06/2024.",
    "CNPJ 11.222.333/0001-81",
]


def _fonte():
    for f in FONTES:
        if Path(f).exists():
            return f
    return None


def _pdf_digital(destino: Path):
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    fonte = _fonte()
    if fonte:
        pdf.add_font("dv", "", fonte)
        pdf.set_font("dv", size=12)
    else:
        pdf.set_font("helvetica", size=12)
    for linha in ATA_TEXTO:
        pdf.cell(0, 10, linha, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(destino))


def _pdf_escaneado(destino: Path):
    """PDF só com imagem (sem camada de texto): simula um documento escaneado."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (2480, 3508), "white")  # A4 a 300 dpi
    d = ImageDraw.Draw(img)
    fonte = ImageFont.truetype(_fonte(), 56)
    y = 300
    for linha in ESCANEADO_TEXTO:
        d.text((220, y), linha, fill="black", font=fonte)
        y += 110
    img.save(destino, "PDF", resolution=300)


SEI_CARIMBO = ("Documento assinado eletronicamente por Fulano de Tal, Servidor, em 21/06/2024, às 10:15, "
               "conforme horário oficial de Brasília. A autenticidade deste documento pode ser conferida no site "
               "sei.cade.gov.br informando o código verificador 1234567 e o código CRC ABCD1234.")


def _pdf_escaneado_com_carimbo(destino: Path):
    """Página escaneada (imagem) com o carimbo digital do SEI por cima: tem texto digital,
    mas o conteúdo está na imagem. O caso que um limiar baixo de texto deixa invisível."""
    from fpdf import FPDF
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (2480, 3508), "white")
    d = ImageDraw.Draw(img)
    fonte = ImageFont.truetype(_fonte(), 56)
    for i, linha in enumerate(["Combinamos o rodízio dos lotes:", "lote 1 fica com a Alfa,",
                               "lote 2 com a Beta. Apague esta mensagem."]):
        d.text((220, 400 + i * 110), linha, fill="black", font=fonte)
    caminho_img = destino.with_suffix(".png")
    img.save(caminho_img)
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(False)  # o carimbo fica no rodapé da mesma página
    pdf.add_page()
    pdf.image(str(caminho_img), x=0, y=0, w=210, h=297)
    pdf.add_font("dv", "", _fonte())
    pdf.set_font("dv", size=7)
    pdf.set_xy(10, 280)
    pdf.multi_cell(190, 3, SEI_CARIMBO)
    pdf.output(str(destino))
    caminho_img.unlink()


ocr_disponivel = pytest.mark.skipif(
    not (localizar_tesseract() and localizar_tessdata("por") and _fonte()),
    reason="Tesseract com 'por' ou fonte TTF indisponível",
)


@pytest.fixture
def caso(tmp_path) -> Caso:
    c = Caso.criar(tmp_path, "caso teste")
    o = c.originais
    (o / "emails").mkdir()
    (o / "emails" / "pregao_12_2024.html").write_text(EMAIL_HTML, encoding="utf-8")
    (o / "boletim.htm").write_text(NEUTRO_HTML, encoding="utf-8")
    (o / "copia_do_boletim.html").write_text(NEUTRO_HTML, encoding="utf-8")  # duplicata
    (o / "planilha.xlsx").write_bytes(b"nao suportado")
    (o / "~$temporario.html").write_text("lixo do Office", encoding="utf-8")
    _pdf_digital(o / "ata_reuniao.pdf")
    if _fonte():
        _pdf_escaneado(o / "termo_escaneado.pdf")
        sei = o / "SEI_08700.000001_2024-00"
        sei.mkdir()
        _pdf_escaneado_com_carimbo(sei / "[12]-1234567_E_mail.pdf")
        anexo = sei / "[13]-7654321_Anexo"
        anexo.mkdir()
        (anexo / "Ata abertura lote 1.html").write_text(
            "<html><body><p>Ata de abertura das propostas do lote 1.</p></body></html>", encoding="utf-8")
    return c
