# Instalador do Olho Vivo e Faro Fino para Windows 10/11.
# Rode clicando duas vezes em instalar.bat (ele chama este arquivo).
# O que faz, nesta ordem (pode rodar de novo quantas vezes quiser: o que já existe é mantido):
#   1. instala o uv (gerenciador de Python), sem precisar de administrador
#   2. instala o Tesseract OCR pelo winget (pede permissão de administrador uma vez)
#   3. baixa o idioma português do OCR para a pasta tessdata do aplicativo
#   4. instala o Python e as bibliotecas do aplicativo (pasta .venv)
#   5. confere a instalação e cria um atalho na área de trabalho

$ErrorActionPreference = "Stop"
$App = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $App
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Passo($texto) { Write-Host ""; Write-Host "==> $texto" -ForegroundColor Cyan }
function Atualiza-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                "$env:USERPROFILE\.local\bin"
}
function Tem-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

# 1. uv --------------------------------------------------------------------------
Passo "1/5 Gerenciador de Python (uv)"
Atualiza-Path
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "uv já instalado."
} else {
    # Instalador oficial: não precisa de administrador; instala em %USERPROFILE%\.local\bin
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    Atualiza-Path
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "Não consegui instalar o uv." }
}

# 2. Tesseract ---------------------------------------------------------------------
Passo "2/5 Tesseract OCR"
$tesseract = @("$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
               "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe",
               "$env:LOCALAPPDATA\Programs\Tesseract-OCR\tesseract.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($tesseract) {
    Write-Host "Tesseract já instalado: $tesseract"
} elseif (Tem-Winget) {
    Write-Host "Instalando pelo winget. Se o Windows pedir permissão de administrador, aceite."
    winget install --id UB-Mannheim.TesseractOCR -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Write-Warning "O winget retornou código $LASTEXITCODE." }
} else {
    Write-Warning "winget não encontrado. Instale o Tesseract manualmente:"
    Write-Warning "  https://github.com/UB-Mannheim/tesseract/wiki  (instalador para Windows)"
    Write-Warning "e rode este instalador de novo."
}

# 3. Português do OCR --------------------------------------------------------------
Passo "3/5 Idioma português do OCR"
$tessdata = Join-Path $App "tessdata"
New-Item -ItemType Directory -Force -Path $tessdata | Out-Null
$por = Join-Path $tessdata "por.traineddata"
if (Test-Path $por) {
    Write-Host "Português já presente."
} else {
    # Modelo padrão do Tesseract (tessdata 4.1.0): equilíbrio entre precisão e velocidade.
    $url = "https://github.com/tesseract-ocr/tessdata/raw/4.1.0/por.traineddata"
    Write-Host "Baixando $url"
    Invoke-WebRequest -Uri $url -OutFile "$por.tmp" -UseBasicParsing
    Move-Item -Force "$por.tmp" $por
}
Write-Host ("SHA-256 do modelo: " + (Get-FileHash $por -Algorithm SHA256).Hash.ToLower())

# 4. Python e bibliotecas --------------------------------------------------------------
Passo "4/5 Python e bibliotecas (pode levar alguns minutos na primeira vez)"
uv sync --no-dev
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as bibliotecas (uv sync)." }

# 5. Conferência e atalho --------------------------------------------------------------
Passo "5/5 Conferência"
uv run --no-dev python -m forense diagnostico
$ok = ($LASTEXITCODE -eq 0)

try {
    $atalho = Join-Path ([Environment]::GetFolderPath("Desktop")) "Olho Vivo e Faro Fino.lnk"
    $ws = New-Object -ComObject WScript.Shell
    $s = $ws.CreateShortcut($atalho)
    $s.TargetPath = Join-Path $App "abrir.bat"
    $s.WorkingDirectory = $App
    $s.Description = "Olho Vivo e Faro Fino: catálogo e triagem de documentos"
    $s.Save()
    Write-Host "Atalho criado na área de trabalho: Olho Vivo e Faro Fino"
} catch {
    Write-Warning "Não consegui criar o atalho; use o abrir.bat."
}

Write-Host ""
if ($ok) {
    Write-Host "Instalação concluída. Para usar: clique duas vezes em 'Olho Vivo e Faro Fino' na área de trabalho." -ForegroundColor Green
} else {
    Write-Host "A instalação terminou com pendências (veja as linhas FALHA acima)." -ForegroundColor Yellow
    Write-Host "Se o Tesseract acabou de ser instalado, feche esta janela e rode o instalador de novo."
}
