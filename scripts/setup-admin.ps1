<#
.SYNOPSIS
  Prepara o ambiente: chave FERNET no .env, administrador (usuário + perfil + vínculo) e token MCP.

.DESCRIPTION
  1. FERNET_KEY: gera a chave no .env se estiver vazia/placeholder (nunca sobrescreve uma chave real:
     trocá-la tornaria ilegíveis as senhas de data source já gravadas, a menos que -ForceNewFernetKey).
  2. docker compose up -d (pule com -NoUp). Na CRIAÇÃO do banco o seed_admin.sh roda sozinho
     (docker-entrypoint-initdb.d) e cria o admin.
  3. Espera o /health do app.
  4. Reexecuta o seed (idempotente), para bancos criados antes do seed ou com análises novas
     (o perfil admin é vinculado a TODAS as análises existentes).
  5. Emite o token por POST /auth/token (o banco só guarda o hash; o token bruto aparece uma vez),
     grava em secrets\admin-token.txt e imprime o trecho de configuração do cliente MCP.

  Roda na raiz do repositório (scripts\setup-admin.ps1) ou na pasta do pacote dist (setup-admin.ps1).
  A senha padrão (Senh@123) é CONHECIDA: troque com  -Password 'nova' -ResetPassword  fora do desenvolvimento.

.EXAMPLE
  .\scripts\setup-admin.ps1
  .\scripts\setup-admin.ps1 -Password 'OutraSenha!1' -ResetPassword
  .\scripts\setup-admin.ps1 -NoUp -ExpireDays 365 -TokenLabel "Claude Desktop"
#>
[CmdletBinding()]
param(
    [string]$Login = "admin",
    [string]$Password = "Senh@123",
    [string]$ComposeFile,            # padrão: docker-compose.local.yml (repositório) ou docker-compose.yml (pacote dist)
    [string]$ProjectName,            # docker compose -p
    [string]$EnvFile = ".env",
    [string]$ApiUrl,                 # padrão: http(s)://localhost:<SERVER_PORT> conforme o .env
    [string]$TokenLabel = "admin-mcp",
    [int]$ExpireDays = 0,            # 0 = padrão do servidor (ACCESS_TOKEN_EXPIRATION_DAYS)
    [string]$TokenFile = "secrets/admin-token.txt",
    [switch]$NoUp,
    [switch]$SkipToken,
    [switch]$ResetPassword,
    [switch]$ForceNewFernetKey
)

$ErrorActionPreference = "Stop"
$DefaultPassword = "Senh@123"
$FernetPlaceholder = "sua_chave_fernet_aqui"

# Raiz do projeto: a pasta deste script se ela tem um compose (pacote dist); senão, a pasta acima (repositório).
$root = $PSScriptRoot
if (-not (Get-ChildItem -Path $root -Filter "docker-compose*.yml" -ErrorAction SilentlyContinue)) {
    $root = Split-Path -Parent $PSScriptRoot
}
Set-Location $root

if (-not $ComposeFile) {
    $ComposeFile = if (Test-Path "docker-compose.local.yml") { "docker-compose.local.yml" } else { "docker-compose.yml" }
}
if (-not (Test-Path $ComposeFile)) { throw "Compose não encontrado: $ComposeFile (rodando em $root)" }

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }

# Caminho absoluto a partir do Set-Location do PowerShell (o diretório do .NET não acompanha o Set-Location);
# aceita caminhos relativos e absolutos.
function Resolve-Full([string]$Path) {
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    # Set-Content do PowerShell 5.1 grava BOM; o .env não pode ter.
    [System.IO.File]::WriteAllText((Resolve-Full $Path), $Text, (New-Object System.Text.UTF8Encoding $false))
}

function New-FernetKey {
    # Idêntico a cryptography.fernet.Fernet.generate_key(): base64 urlsafe de 32 bytes aleatórios (44 chars).
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_')
}

# ---- 1) .env + FERNET_KEY ---------------------------------------------------------------------
Write-Step "[1/5] Chave FERNET em $EnvFile"
if (-not (Test-Path $EnvFile)) {
    if (-not (Test-Path ".env.example")) { throw "$EnvFile não existe e não há .env.example para copiar." }
    Copy-Item ".env.example" $EnvFile
    Write-Host "    $EnvFile criado a partir do .env.example"
}
$envText = [System.IO.File]::ReadAllText((Resolve-Full $EnvFile))
$current = if ($envText -match '(?m)^FERNET_KEY=(.*)$') { $Matches[1].Trim() } else { "" }

if ($ForceNewFernetKey -or [string]::IsNullOrEmpty($current) -or $current -eq $FernetPlaceholder) {
    if ($ForceNewFernetKey -and $current -and $current -ne $FernetPlaceholder) {
        Write-Warning "Trocando uma FERNET_KEY existente: as senhas de data source já gravadas ficam ilegíveis até serem recifradas."
    }
    $newKey = New-FernetKey
    $envText = if ($envText -match '(?m)^FERNET_KEY=') {
        [regex]::Replace($envText, '(?m)^FERNET_KEY=.*$', { param($m) "FERNET_KEY=$newKey" })
    } else { $envText.TrimEnd() + "`nFERNET_KEY=$newKey`n" }
    Write-Utf8NoBom $EnvFile $envText
    Write-Host "    FERNET_KEY gerada e gravada em $EnvFile"
}
else {
    if ($current -notmatch '^[A-Za-z0-9_-]{43}=$') { Write-Warning "FERNET_KEY existente não parece uma chave Fernet válida (44 caracteres base64 url-safe)." }
    Write-Host "    FERNET_KEY já definida: mantida"
}
if ($envText -match '(?m)^POSTGRES_CONFIG_PASSWORD=changeme\s*$') {
    Write-Warning "POSTGRES_CONFIG_PASSWORD ainda é 'changeme'. Em banco novo ela vira a senha do Postgres; troque no $EnvFile antes de criar o banco."
}

# ---- compose helper ---------------------------------------------------------------------------
$dc = @("compose")
if ($ProjectName) { $dc += @("-p", $ProjectName) }
$dc += @("-f", $ComposeFile, "--env-file", $EnvFile)
function Invoke-Dc {
    & docker @dc @args
    if ($LASTEXITCODE -ne 0) { throw "docker $($dc -join ' ') $($args -join ' ') falhou (exit $LASTEXITCODE)" }
}

# URL da API: porta/TLS vêm do .env
if (-not $ApiUrl) {
    $port = if ($envText -match '(?m)^SERVER_PORT=(\d+)') { $Matches[1] } else { "3000" }
    $scheme = if ($envText -match '(?m)^TLS_ENABLED=false') { "http" } else { "https" }
    $ApiUrl = "${scheme}://localhost:$port"
}
$ApiUrl = $ApiUrl.TrimEnd('/')

# Certificado do mkcert não é confiado por padrão: só ignoramos a validação para localhost.
$tlsArgs = @{}
if ([uri]$ApiUrl -and ([uri]$ApiUrl).Host -in @("localhost", "127.0.0.1", "::1")) {
    if ($PSVersionTable.PSEdition -eq "Core") { $tlsArgs.SkipCertificateCheck = $true }
    else {
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    }
}

# ---- 2) subir ---------------------------------------------------------------------------------
if ($NoUp) { Write-Step "[2/5] docker compose up -d: pulado (-NoUp)" }
else {
    Write-Step "[2/5] docker compose up -d (o seed do admin roda sozinho se o banco for criado agora)"
    Invoke-Dc up -d
}

# ---- 3) health --------------------------------------------------------------------------------
Write-Step "[3/5] Aguardando $ApiUrl/health"
$deadline = (Get-Date).AddSeconds(120)
$healthy = $false
while ((Get-Date) -lt $deadline) {
    try {
        $h = Invoke-RestMethod -Uri "$ApiUrl/health" -TimeoutSec 5 @tlsArgs
        if ($h.status -eq "ok") { $healthy = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $healthy) { throw "O app não respondeu 'ok' em $ApiUrl/health em 120 s. Veja: docker $($dc -join ' ') logs app" }
Write-Host "    app e banco no ar"

# ---- 4) seed (idempotente) --------------------------------------------------------------------
Write-Step "[4/5] Administrador '$Login' (usuário + perfil admin + vínculos)"
$reset = if ($ResetPassword) { "1" } else { "0" }
try {
    Invoke-Dc exec -T -e "ADMIN_LOGIN=$Login" -e "ADMIN_PASSWORD=$Password" -e "ADMIN_RESET_PASSWORD=$reset" `
        postgres sh /docker-entrypoint-initdb.d/02-seed-admin.sh
}
catch {
    throw "Falha ao executar o seed no container postgres. Se ele foi criado antes desta versão, o arquivo " +
          "02-seed-admin.sh não está montado: rode sem -NoUp (o 'up -d' recria o postgres com o volume de dados preservado). $_"
}
if ($ResetPassword) { Write-Host "    senha do admin regravada (-ResetPassword)" }

# ---- 5) token ---------------------------------------------------------------------------------
if ($SkipToken) { Write-Step "[5/5] Token: pulado (-SkipToken)"; return }

Write-Step "[5/5] Token de acesso (POST /auth/token)"
$body = @{ email = $Login; password = $Password; label = $TokenLabel }
if ($ExpireDays -gt 0) { $body.expire_days = $ExpireDays }
try {
    $resp = Invoke-RestMethod -Method Post -Uri "$ApiUrl/auth/token" -ContentType "application/json" `
        -Body ($body | ConvertTo-Json -Compress) @tlsArgs
}
catch {
    $status = try { [int]$_.Exception.Response.StatusCode } catch { 0 }
    if ($status -eq 401) {
        throw "401: login ou senha não conferem. Se o admin '$Login' já existia com outra senha, rode de novo com -ResetPassword."
    }
    throw "Falha ao emitir o token (HTTP $status): $($_.Exception.Message)"
}

New-Item -ItemType Directory -Force -Path (Split-Path $TokenFile -Parent) | Out-Null
Write-Utf8NoBom $TokenFile ($resp.token + "`n")

$mcpUrl = "$ApiUrl/mcp"
Write-Host ""
Write-Host "Pronto." -ForegroundColor Green
Write-Host "  Login:      $Login"
Write-Host "  Token:      $($resp.token)"
Write-Host "  Expira em:  $($resp.expires_at)"
Write-Host "  Salvo em:   $TokenFile   (fora do git; o token NÃO pode ser recuperado depois)"
Write-Host ""
Write-Host "Cliente MCP (Claude Desktop com mcp-remote):"
Write-Host @"
"analise-dados": {
  "command": "npx",
  "args": ["mcp-remote", "$mcpUrl", "--header", "Authorization:`${AUTH_HEADER}"],
  "env": {"NODE_OPTIONS": "--use-system-ca", "AUTH_HEADER": "Bearer $($resp.token)"}
}
"@
if ($Password -eq $DefaultPassword) {
    Write-Host ""
    $self = if ($PSScriptRoot -eq $root) { ".\setup-admin.ps1" } else { ".\scripts\setup-admin.ps1" }   # pacote dist x repositório
    Write-Warning "A senha do admin é a PADRÃO e é conhecida. Troque com: $self -NoUp -Password 'nova' -ResetPassword"
}
