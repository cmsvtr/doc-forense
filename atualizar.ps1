# Atualiza o doc-forense com a versão mais recente do GitHub.
# Troca só o código: a pasta casos (os seus documentos e resultados), o Python instalado (.venv)
# e o idioma do OCR (tessdata) ficam como estão. Feche o doc-forense antes de atualizar.

$ErrorActionPreference = "Stop"
$Ramo = "claude/prompt-forense-analysis-3qt99j"
$App = Split-Path -Parent $MyInvocation.MyCommand.Path
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [Environment]::GetEnvironmentVariable("Path", "User") + ";" + "$env:USERPROFILE\.local\bin"

$tmp = Join-Path $env:TEMP ("doc-forense-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    Write-Host "==> Baixando a versão mais recente ($Ramo)" -ForegroundColor Cyan
    $zip = Join-Path $tmp "doc-forense.zip"
    Invoke-WebRequest -Uri "https://github.com/cmsvtr/doc-forense/archive/refs/heads/$Ramo.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $origem = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1

    Write-Host "==> Copiando o código (casos, .venv e tessdata não são tocados)" -ForegroundColor Cyan
    # /E copia subpastas; sem /MIR nada é apagado no destino. Códigos 0-7 do robocopy são sucesso.
    robocopy $origem.FullName $App /E /XD casos .venv tessdata /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Falha ao copiar os arquivos (robocopy $LASTEXITCODE)." }

    Write-Host "==> Conferindo as bibliotecas" -ForegroundColor Cyan
    Set-Location $App
    uv sync --no-dev
    if ($LASTEXITCODE -ne 0) { throw "Falha ao atualizar as bibliotecas (uv sync)." }
    uv run --no-dev python -m forense diagnostico
    Write-Host ""
    Write-Host "Atualizado. Abra o doc-forense de novo; para continuar um processamento, clique em Processar." -ForegroundColor Green
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
