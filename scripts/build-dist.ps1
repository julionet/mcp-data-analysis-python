<#
.SYNOPSIS
  Gera o pacote para rodar a aplicação em OUTRO computador, sem o código-fonte.

.DESCRIPTION
  1. docker compose -f docker-compose.dist.yml build   (imagem do app, tag <Image>:<Version>)
  2. docker pull <PostgresImage>                        (para o destino funcionar sem internet)
  3. docker save <app> <postgres> -o dist\<Image>-<Version>.tar
  4. copia para dist\: docker-compose.yml, schema.sql, .env.example, certs\, INSTALL.md, SHA256SUMS.txt

  Rode da raiz do repositório ou de qualquer pasta (o script entra na raiz sozinho).
  O pacote NÃO leva .env nem certificados (segredos); o .env.example gerado aqui precisa ser
  mantido em sincronia com as variáveis do docker-compose.dist.yml.

.EXAMPLE
  .\scripts\build-dist.ps1 -Version 1.0.0
  .\scripts\build-dist.ps1 -Version 1.1.0 -PostgresImage postgres:16.6
#>
param(
    [string]$Version = "1.0.0",
    [string]$Image = "mcp-analysis",
    [string]$PostgresImage = "postgres:16",
    [string]$OutDir = "dist"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)   # raiz do repositório

function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "docker $($args -join ' ') falhou (exit $LASTEXITCODE)" }
}

function Write-TextFile([string]$Path, [string]$Text) {
    # UTF-8 SEM BOM (o BOM do Set-Content do PowerShell 5.1 quebra `sha256sum -c` e o .env)
    [System.IO.File]::WriteAllText((Join-Path (Get-Location) $Path), $Text, (New-Object System.Text.UTF8Encoding $false))
}

$appImage = "${Image}:${Version}"
$tarName = "${Image}-${Version}.tar"
$tarPath = Join-Path $OutDir $tarName

foreach ($required in @("docker-compose.dist.yml", "Dockerfile", "src/database/schema.sql", "src/database/seed_admin.sh", "scripts/setup-admin.ps1", ".env.example")) {
    if (-not (Test-Path $required)) { throw "Arquivo obrigatório não encontrado: $required" }
}
Invoke-Docker info --format "{{.ServerVersion}}" | Out-Null   # daemon no ar?

# 1) Build. Segredos fictícios só para o compose interpolar (o build não os grava na imagem).
Write-Host "==> [1/4] Build de $appImage" -ForegroundColor Cyan
$env:APP_IMAGE = $Image
$env:APP_VERSION = $Version
$env:POSTGRES_IMAGE = $PostgresImage
$env:POSTGRES_CONFIG_PASSWORD = "build-only"
$env:FERNET_KEY = "build-only"
try {
    Invoke-Docker compose -f docker-compose.dist.yml build app
}
finally {
    Remove-Item Env:APP_IMAGE, Env:APP_VERSION, Env:POSTGRES_IMAGE, Env:POSTGRES_CONFIG_PASSWORD, Env:FERNET_KEY -ErrorAction SilentlyContinue
}

# 2) Postgres local (o save só inclui imagens que já estão no daemon)
Write-Host "==> [2/4] Baixando $PostgresImage" -ForegroundColor Cyan
Invoke-Docker pull $PostgresImage

# 3) Pasta de saída + docker save
Write-Host "==> [3/4] docker save -> $tarPath (pode levar alguns minutos)" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $OutDir, (Join-Path $OutDir "certs") | Out-Null
Invoke-Docker save $appImage $PostgresImage -o $tarPath

# 4) Arquivos que acompanham o .tar
Write-Host "==> [4/4] Montando o pacote em $OutDir\" -ForegroundColor Cyan
Copy-Item docker-compose.dist.yml (Join-Path $OutDir "docker-compose.yml") -Force
Copy-Item src/database/schema.sql (Join-Path $OutDir "schema.sql") -Force
Copy-Item src/database/seed_admin.sh (Join-Path $OutDir "seed_admin.sh") -Force   # LF (ver .gitattributes)
Copy-Item scripts/setup-admin.ps1 (Join-Path $OutDir "setup-admin.ps1") -Force

Write-TextFile (Join-Path $OutDir ".env.example") @"
# Copie para .env (cp .env.example .env) e preencha. O .env fica ao lado do docker-compose.yml.

# Versão da imagem carregada pelo `docker load` (NÃO mude sem carregar o .tar da nova versão)
APP_IMAGE=$Image
APP_VERSION=$Version
POSTGRES_IMAGE=$PostgresImage

SERVER_PORT=3000
# TLS no próprio app; certificados em .\certs (server.pem e server-key.pem). Clientes MCP exigem
# HTTPS confiável: a CA que assinou o certificado precisa estar instalada na máquina do cliente.
TLS_ENABLED=true
TLS_CERT_FILE=certs/server.pem
TLS_KEY_FILE=certs/server-key.pem

POSTGRES_CONFIG_DATABASE=analysis_config
POSTGRES_CONFIG_USER=postgres
POSTGRES_CONFIG_PASSWORD=changeme
POSTGRES_HOST_PORT=5433

# Administrador criado na criação do banco (seed_admin.sh) e pelo setup-admin.ps1.
# SENHA PADRÃO CONHECIDA (Senh@123): troque antes de expor o servidor. Com "`$" na senha, escreva "`$`$".
# Mudar aqui NÃO altera um admin que já existe: .\setup-admin.ps1 -NoUp -Password 'nova' -ResetPassword
# ADMIN_LOGIN=admin
# ADMIN_PASSWORD=Senh@123

# FERNET_KEY: o setup-admin.ps1 gera e preenche. Manualmente, gere com:  docker run --rm $appImage python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FERNET_KEY=sua_chave_fernet_aqui

DEFAULT_MAX_RESULT_ROWS=500
DEFAULT_MAX_RESULT_SIZE_KB=150
QUERY_TIMEOUT_SECONDS=30
QUERY_RETRY_MAX_ATTEMPTS=3
QUERY_RETRY_BACKOFF_BASE_MS=200
CACHE_BACKEND=memory
CACHE_MAX_ENTRIES=200
CACHE_MAX_SIZE_MB=100
ACCESS_TOKEN_EXPIRATION_DAYS=90
ACCESS_TOKEN_MAX_EXPIRATION_DAYS=365
"@

Write-TextFile (Join-Path $OutDir "certs/LEIA-ME.txt") "Coloque aqui server.pem e server-key.pem (certificado e chave TLS do servidor).`n"

Write-TextFile (Join-Path $OutDir "INSTALL.md") @"
# Instalação ($appImage)

Requisitos: Docker (com Compose v2) e as portas 3000 e 5433 livres (ajustáveis no ``.env``).

1. **Carregar as imagens** (app + $PostgresImage, não precisa de internet):
   ``docker load -i $tarName``
2. **Configurar:** ``cp .env.example .env`` e trocar ``POSTGRES_CONFIG_PASSWORD`` (a ``FERNET_KEY`` é gerada no passo 4).
3. **Certificados:** copiar ``server.pem`` e ``server-key.pem`` para ``certs/``.
4. **Subir e criar o administrador** (PowerShell): ``.\setup-admin.ps1``
   Gera a ``FERNET_KEY`` no ``.env`` (se ainda for o placeholder), sobe o compose, cria o admin
   (login ``admin``, senha padrão ``Senh@123``, perfil ``admin`` com acesso a todas as análises), emite o token
   de acesso e o salva em ``secrets\admin-token.txt`` (aparece uma única vez; imprime também o trecho de
   configuração do cliente MCP). **Troque a senha padrão**: ``.\setup-admin.ps1 -NoUp -Password 'nova' -ResetPassword``.
5. **Conferir:** ``curl -k https://localhost:3000/health``  →  ``{"status":"ok","db":true}``

**Sem PowerShell (Linux):** gere a chave ``docker run --rm $appImage python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``
e ponha em ``FERNET_KEY`` no ``.env``; ``docker compose up -d`` cria o admin sozinho (seed na criação do banco);
o token vem de ``curl -k -X POST https://localhost:3000/auth/token -H "Content-Type: application/json" -d '{"email":"admin","password":"Senh@123"}'``.

O admin só é criado automaticamente quando o banco é criado (volume vazio). Análises cadastradas depois não ficam
visíveis ao admin até reexecutar ``.\setup-admin.ps1 -NoUp`` (ele vincula o perfil a todas as análises existentes).
Demais usuários, perfis e análises: INSERT direto no banco (sem CRUD em V1.0).

## Atualizar para uma nova versão
1. ``docker load -i <novo>.tar``
2. Ajustar ``APP_VERSION`` no ``.env`` para a nova versão.
3. ``docker compose up -d`` (recria só o ``app``; o volume do banco é preservado).
4. Se a versão trouxe mudança de schema, aplicar à mão no banco existente (o ``schema.sql`` só roda com
   o volume vazio). Ex.: ``docker compose exec postgres psql -U postgres -d analysis_config -c "ALTER TABLE ..."``

## Não faça
``docker compose down -v`` apaga o volume do banco (usuários, análises e histórico).

## Integridade
``SHA256SUMS.txt`` traz o hash do ``.tar``. No Linux: ``sha256sum -c SHA256SUMS.txt``;
no Windows: ``Get-FileHash $tarName -Algorithm SHA256``.
"@

$hash = (Get-FileHash $tarPath -Algorithm SHA256).Hash.ToLower()
Write-TextFile (Join-Path $OutDir "SHA256SUMS.txt") "$hash  $tarName`n"

$sizeMb = [math]::Round((Get-Item $tarPath).Length / 1MB)
Write-Host ""
Write-Host "Pacote pronto em $OutDir\ ($tarName = $sizeMb MB)" -ForegroundColor Green
Write-Host "Copie a pasta inteira para o outro computador e siga o INSTALL.md."
