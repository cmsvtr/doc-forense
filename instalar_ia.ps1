# Instala a IA local do Olho Vivo e Faro Fino: o Ollama (programa que roda modelos de IA neste computador)
# e o modelo Qwen 2.5 7B. Nada é enviado para fora: o modelo roda aqui, sem internet.
# Não precisa de administrador: o Ollama se instala na pasta do usuário.
# Pode rodar de novo quantas vezes quiser: o que já existe é mantido.

$ErrorActionPreference = "Stop"
$Modelo = "qwen2.5:7b"          # ~4,7 GB
$App = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $App
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Passo($texto) { Write-Host ""; Write-Host "==> $texto" -ForegroundColor Cyan }
function Atualiza-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                "$env:USERPROFILE\.local\bin;$env:LOCALAPPDATA\Programs\Ollama"
}
function Ollama-Ativo {
    try { Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 3 | Out-Null; return $true }
    catch { return $false }
}

# 1. Ollama ------------------------------------------------------------------------
Passo "1/4 Ollama"
Atualiza-Path
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "Ollama já instalado."
} else {
    $setup = Join-Path $env:TEMP "OllamaSetup.exe"
    Write-Host "Baixando o instalador do Ollama (cerca de 1 GB)..."
    Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $setup -UseBasicParsing
    Write-Host "Instalando (sem administrador)..."
    $p = Start-Process -FilePath $setup -ArgumentList "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
    if ($p.ExitCode -ne 0) {
        Write-Warning "A instalação silenciosa retornou $($p.ExitCode). Abrindo o instalador normal: siga as telas."
        Start-Process -FilePath $setup -Wait
    }
    Remove-Item $setup -ErrorAction SilentlyContinue
    Atualiza-Path
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { throw "O Ollama não foi encontrado depois da instalação." }
}

# 2. Serviço ativo -----------------------------------------------------------------
Passo "2/4 Iniciando o Ollama"
if (-not (Ollama-Ativo)) {
    $app = "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
    if (Test-Path $app) { Start-Process -FilePath $app } else { Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden }
    for ($i = 0; $i -lt 60 -and -not (Ollama-Ativo); $i++) { Start-Sleep -Seconds 2 }
}
if (-not (Ollama-Ativo)) { throw "O Ollama não respondeu em http://127.0.0.1:11434. Abra-o pelo menu Iniciar e rode este instalador de novo." }
Write-Host "Ollama ativo em http://127.0.0.1:11434 (só neste computador)."
if ($env:OLLAMA_HOST -and $env:OLLAMA_HOST -notmatch "^(127\.0\.0\.1|localhost)") {
    Write-Warning "OLLAMA_HOST = $($env:OLLAMA_HOST). O Ollama pode estar aceitando conexões da rede. O seguro é não definir essa variável."
}

# 3. Modelo ------------------------------------------------------------------------
Passo "3/4 Modelo $Modelo"
$livre = (Get-PSDrive -Name ($env:USERPROFILE.Substring(0, 1))).Free / 1GB
if ($livre -lt 8) { Write-Warning ("Pouco espaço livre no disco ({0:N1} GB). O modelo precisa de cerca de 5 GB." -f $livre) }
$tem = (ollama list) -match [regex]::Escape($Modelo)
if ($tem) {
    Write-Host "Modelo já baixado."
} else {
    Write-Host "Baixando o modelo (cerca de 4,7 GB; pode levar de 10 a 40 minutos)..."
    ollama pull $Modelo
    if ($LASTEXITCODE -ne 0) { throw "Falha ao baixar o modelo. Rode este instalador de novo: o download continua de onde parou." }
}

# 3b. Modelo da busca por significado ------------------------------------------------
$ModeloVetores = "bge-m3"       # ~1,2 GB
if ((ollama list) -match [regex]::Escape($ModeloVetores)) {
    Write-Host "Modelo de busca por significado ($ModeloVetores) já baixado."
} else {
    Write-Host "Baixando o modelo da busca por significado ($ModeloVetores, cerca de 1,2 GB)..."
    ollama pull $ModeloVetores
    if ($LASTEXITCODE -ne 0) { Write-Warning "Falha ao baixar $ModeloVetores. A busca por palavra continua funcionando; rode o instalador de novo depois." }
}

# 4. Teste -------------------------------------------------------------------------
Passo "4/4 Teste de velocidade (a primeira resposta é mais lenta: o modelo é carregado na memória)"
uv run --no-dev python -m forense ia --modelo $Modelo
$ok = ($LASTEXITCODE -eq 0)

Write-Host ""
if ($ok) {
    Write-Host "IA local instalada e funcionando." -ForegroundColor Green
} else {
    Write-Host "A IA foi instalada, mas o teste não passou. Copie as linhas acima e mande para análise." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Sigilo: use só modelos que rodam aqui. Modelos com 'cloud' no nome rodam na nuvem da Ollama;"
Write-Host "não os use, e não é preciso entrar com conta no aplicativo do Ollama."
