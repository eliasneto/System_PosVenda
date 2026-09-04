##
##  setup.ps1 - Configuracao e execucao do RPA EACE NF
##  Execute via setup.bat (duplo clique).
##

Set-Location $PSScriptRoot

function Write-Step { param($msg) Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "   [OK] $msg" -ForegroundColor Green }
function Write-Fail {
    param($msg)
    Write-Host "   [ERRO] $msg" -ForegroundColor Red
    Read-Host "`nPressione Enter para fechar"
    exit 1
}

Write-Host ""


# --- 1. Python ---
Write-Step "1/6  Verificando Python..."

$pythonExe = $null
foreach ($cmd in @("python", "py")) {
    try {
        $v = & $cmd --version 2>&1
        if ($v -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 9) {
            $pythonExe = $cmd
            Write-OK "Encontrado: $v"
            break
        }
    } catch {}
}

if (-not $pythonExe) {
    Write-Host "   Python 3.9+ nao encontrado. Baixando instalador (~26 MB)..." -ForegroundColor Yellow

    $pythonUrl  = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
    $instalador = "$env:TEMP\python-3.12.10-amd64.exe"

    try {
        Invoke-WebRequest -Uri $pythonUrl -OutFile $instalador -UseBasicParsing
    } catch {
        Write-Fail "Nao foi possivel baixar o Python. Verifique a conexao com a internet e tente novamente. Erro: $_"
    }

    $proc = Start-Process -FilePath $instalador `
        -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" `
        -Wait -PassThru

    Remove-Item $instalador -Force -ErrorAction SilentlyContinue

    if ($proc.ExitCode -ne 0) {
        Write-Fail "Falha ao instalar Python (codigo $($proc.ExitCode)). Instale manualmente em https://python.org e execute novamente."
    }

    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH", "User")
    $pythonExe = "python"
    Write-OK "Python 3.12 instalado com sucesso."
}


# --- 2. Ambiente virtual ---
Write-Step "2/6  Configurando ambiente virtual..."

$venvValido = $false
if (Test-Path ".venv\Scripts\python.exe") {
    try {
        & ".venv\Scripts\python.exe" --version 2>&1 | Out-Null
        $venvValido = ($LASTEXITCODE -eq 0)
    } catch {}
}

if (-not $venvValido) {
    if (Test-Path ".venv") {
        Write-Host "   Ambiente virtual invalido ou de outro caminho. Recriando..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force ".venv"
    }
    & $pythonExe -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Fail "Falha ao criar o ambiente virtual (.venv)." }
    Write-OK "Ambiente virtual criado."
} else {
    Write-OK "Ambiente virtual ja existe e esta valido."
}


# --- 3. Dependencias ---
Write-Step "3/6  Instalando dependencias Python..."

& ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet --no-cache-dir
if ($LASTEXITCODE -ne 0) { Write-Fail "Falha ao instalar dependencias (requirements.txt)." }
Write-OK "Dependencias instaladas."


# --- 4. Playwright / Chromium ---
Write-Step "4/6  Verificando navegador Chromium (pode demorar na 1a vez ~120 MB)..."

& ".venv\Scripts\playwright.exe" install chromium
if ($LASTEXITCODE -ne 0) { Write-Fail "Falha ao instalar o Chromium." }
Write-OK "Chromium pronto."


# --- 5. Arquivo .env ---
Write-Step "5/6  Verificando configuracoes de acesso (.env)..."

if (-not (Test-Path ".env")) {
    Write-Host ""
    Write-Host "   Preencha as informacoes de acesso ao portal EACE:" -ForegroundColor Yellow
    Write-Host "   (A senha nao aparecera na tela por seguranca)" -ForegroundColor Gray
    Write-Host ""

    $usuario = Read-Host "   E-mail de acesso"

    $senhaSecure = Read-Host "   Senha" -AsSecureString
    $BSTR  = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($senhaSecure)
    $senha = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)

    $linhas = @(
        "EACE_URL=https://eace.org.br/login?login=login",
        "EACE_USUARIO=$usuario",
        "EACE_SENHA=$senha",
        "HEADLESS=false",
        "TIMEOUT_MS=30000",
        "DELAY_MS=1500"
    )
    $conteudo = $linhas -join "`n"

    $utf8SemBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText("$PSScriptRoot\.env", $conteudo, $utf8SemBom)

    Write-OK ".env criado com as credenciais informadas."
} else {
    Write-OK ".env ja configurado - credenciais mantidas."
}


# --- 6. Pastas ---
Write-Step "6/6  Criando estrutura de pastas..."

$pastas = @("input", "input\EACE", "output", "config\logs", "config\screenshots")
foreach ($pasta in $pastas) {
    if (-not (Test-Path $pasta)) {
        New-Item -ItemType Directory -Force -Path $pasta | Out-Null
        Write-OK "Criada: $pasta"
    }
}
Write-OK "Estrutura de pastas OK."


# --- Execucao ---
Write-Host ""
Write-Host "+----------------------------------------------------+" -ForegroundColor Green
Write-Host "|         Tudo pronto! Iniciando automacao...        |" -ForegroundColor Green
Write-Host "+----------------------------------------------------+" -ForegroundColor Green
Write-Host ""

& ".venv\Scripts\python.exe" src\main.py

Write-Host ""
Read-Host "Pressione Enter para fechar"
