#!/usr/bin/env bash
# Gera o pacote para rodar a aplicação em OUTRO computador, sem o código-fonte (macOS/Linux).
# Equivalente a scripts/build-dist.ps1.
#
#   1. docker compose -f docker-compose.dist.yml build app   (imagem <image>:<version>)
#   2. docker pull <postgres-image>                          (para o destino funcionar sem internet)
#   3. docker save <app> <postgres> -o dist/<image>-<version>.tar
#   4. copia para dist/: docker-compose.yml, schema.sql, seed_admin.sh, setup-admin.ps1/.sh,
#      .env.example, certs/, INSTALL.md, SHA256SUMS.txt
#
# Uso (de qualquer pasta):
#   ./scripts/build-dist.sh
#   ./scripts/build-dist.sh --version 1.1.0 --postgres-image postgres:16.6
#
# O pacote NÃO leva .env nem certificados (segredos).

set -euo pipefail

VERSION="1.0.0"
IMAGE="mcp-analysis"
POSTGRES_IMAGE="postgres:16"
OUT_DIR="dist"

usage() {
    cat <<'EOF'
Uso: ./scripts/build-dist.sh [opções]

  --version <v>            versão do pacote (padrão: 1.0.0)
  --image <nome>           nome da imagem do app (padrão: mcp-analysis)
  --postgres-image <img>   imagem do Postgres (padrão: postgres:16)
  --out-dir <pasta>        pasta de saída (padrão: dist)
  -h, --help               mostra esta ajuda
EOF
}

die() {
    printf '\033[0;31mERRO: %s\033[0m\n' "$1" >&2
    exit 1
}

step() {
    printf '\033[0;36m==> %s\033[0m\n' "$1"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --version|--image|--postgres-image|--out-dir)
            [[ $# -ge 2 ]] || die "a opção $1 precisa de um valor"
            case "$1" in
                --version) VERSION="$2" ;;
                --image) IMAGE="$2" ;;
                --postgres-image) POSTGRES_IMAGE="$2" ;;
                --out-dir) OUT_DIR="$2" ;;
            esac
            shift 2
            ;;
        *) die "opção desconhecida: $1 (use --help)" ;;
    esac
done

cd "$(dirname "${BASH_SOURCE[0]}")/.."

APP_TAG="${IMAGE}:${VERSION}"
TAR_NAME="${IMAGE}-${VERSION}.tar"
TAR_PATH="${OUT_DIR}/${TAR_NAME}"

for required in docker-compose.dist.yml Dockerfile src/database/schema.sql src/database/seed_admin.sh \
                scripts/setup-admin.ps1 scripts/setup-admin.sh .env.example; do
    [[ -f "$required" ]] || die "arquivo obrigatório não encontrado: $required"
done

docker info >/dev/null 2>&1 || die "o Docker não está rodando. Abra o Docker Desktop e tente de novo."

# 1) Build. Segredos fictícios só para o compose interpolar (o build não os grava na imagem).
step "[1/4] Build de $APP_TAG"
APP_IMAGE="$IMAGE" APP_VERSION="$VERSION" POSTGRES_IMAGE="$POSTGRES_IMAGE" \
POSTGRES_CONFIG_PASSWORD="build-only" FERNET_KEY="build-only" \
    docker compose -f docker-compose.dist.yml build app

# 2) Postgres local (o save só inclui imagens que já estão no daemon)
step "[2/4] Baixando $POSTGRES_IMAGE"
docker pull "$POSTGRES_IMAGE"

# 3) Pasta de saída + docker save
step "[3/4] docker save -> $TAR_PATH (pode levar alguns minutos)"
mkdir -p "$OUT_DIR/certs"
docker save "$APP_TAG" "$POSTGRES_IMAGE" -o "$TAR_PATH"

# 4) Arquivos que acompanham o .tar
step "[4/4] Montando o pacote em $OUT_DIR/"
cp docker-compose.dist.yml "$OUT_DIR/docker-compose.yml"
cp src/database/schema.sql "$OUT_DIR/schema.sql"
cp src/database/seed_admin.sh "$OUT_DIR/seed_admin.sh"
cp scripts/setup-admin.ps1 "$OUT_DIR/setup-admin.ps1"
cp scripts/setup-admin.sh "$OUT_DIR/setup-admin.sh"
chmod +x "$OUT_DIR/setup-admin.sh"

# Substitui os marcadores @@...@@ dos textos abaixo pelos valores desta build.
render() {
    sed -e "s|@@IMAGE@@|$IMAGE|g" -e "s|@@VERSION@@|$VERSION|g" \
        -e "s|@@APP_IMAGE@@|$APP_TAG|g" -e "s|@@POSTGRES_IMAGE@@|$POSTGRES_IMAGE|g" \
        -e "s|@@TAR_NAME@@|$TAR_NAME|g"
}

render > "$OUT_DIR/.env.example" <<'EOF'
# Copie para .env (cp .env.example .env) e preencha. O .env fica ao lado do docker-compose.yml.

# Versão da imagem carregada pelo `docker load` (NÃO mude sem carregar o .tar da nova versão)
APP_IMAGE=@@IMAGE@@
APP_VERSION=@@VERSION@@
POSTGRES_IMAGE=@@POSTGRES_IMAGE@@

SERVER_PORT=3000
# TLS no próprio app; certificados em ./certs (server.pem e server-key.pem). Clientes MCP exigem
# HTTPS confiável: a CA que assinou o certificado precisa estar instalada na máquina do cliente.
TLS_ENABLED=true
TLS_CERT_FILE=certs/server.pem
TLS_KEY_FILE=certs/server-key.pem

POSTGRES_CONFIG_DATABASE=analysis_config
POSTGRES_CONFIG_USER=postgres
POSTGRES_CONFIG_PASSWORD=changeme
POSTGRES_HOST_PORT=5433

# Administrador criado na criação do banco (seed_admin.sh) e pelo setup-admin.
# SENHA PADRÃO CONHECIDA (Senh@123): troque antes de expor o servidor. Com "$" na senha, escreva "$$".
# Mudar aqui NÃO altera um admin que já existe: ./setup-admin.sh --no-up --password 'nova' --reset-password
# ADMIN_LOGIN=admin
# ADMIN_PASSWORD=Senh@123

# FERNET_KEY: o setup-admin gera e preenche. Manualmente, gere com:
#   docker run --rm @@APP_IMAGE@@ python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
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
EOF

printf '%s\n' "Coloque aqui server.pem e server-key.pem (certificado e chave TLS do servidor)." > "$OUT_DIR/certs/LEIA-ME.txt"

render > "$OUT_DIR/INSTALL.md" <<'EOF'
# Instalação (@@APP_IMAGE@@)

Requisitos: Docker (com Compose v2) e as portas 3000 e 5433 livres (ajustáveis no `.env`).

1. **Carregar as imagens** (app + @@POSTGRES_IMAGE@@, não precisa de internet):
   `docker load -i @@TAR_NAME@@`
2. **Configurar:** `cp .env.example .env` e trocar `POSTGRES_CONFIG_PASSWORD` (a `FERNET_KEY` é gerada no passo 4).
3. **Certificados:** copiar `server.pem` e `server-key.pem` para `certs/`.
4. **Subir e criar o administrador:**
   - macOS/Linux: `./setup-admin.sh`
   - Windows (PowerShell): `.\setup-admin.ps1`

   Gera a `FERNET_KEY` no `.env` (se ainda for o placeholder), sobe o compose, cria o admin
   (login `admin`, senha padrão `Senh@123`, perfil `admin` com acesso a todas as análises), emite o token
   de acesso e o salva em `secrets/admin-token.txt` (aparece uma única vez; imprime também o trecho de
   configuração do cliente MCP). **Troque a senha padrão:** `./setup-admin.sh --no-up --password 'nova' --reset-password`
   (no Windows: `.\setup-admin.ps1 -NoUp -Password 'nova' -ResetPassword`).
5. **Conferir:** `curl -k https://localhost:3000/health`  →  `{"status":"ok","db":true}`

**Sem script:** gere a chave com `docker run --rm @@APP_IMAGE@@ python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
e ponha em `FERNET_KEY` no `.env`; `docker compose up -d` cria o admin sozinho (seed na criação do banco);
o token vem de `curl -k -X POST https://localhost:3000/auth/token -H "Content-Type: application/json" -d '{"email":"admin","password":"Senh@123"}'`.

O admin só é criado automaticamente quando o banco é criado (volume vazio). Análises cadastradas depois não ficam
visíveis ao admin até reexecutar o `setup-admin` com `--no-up` (ele vincula o perfil a todas as análises existentes).
Demais usuários, perfis e análises: INSERT direto no banco (sem CRUD em V1.0).

## Atualizar para uma nova versão
1. `docker load -i <novo>.tar`
2. Ajustar `APP_VERSION` no `.env` para a nova versão.
3. `docker compose up -d` (recria só o `app`; o volume do banco é preservado).
4. Se a versão trouxe mudança de schema, aplicar à mão no banco existente (o `schema.sql` só roda com
   o volume vazio). Ex.: `docker compose exec postgres psql -U postgres -d analysis_config -c "ALTER TABLE ..."`

## Não faça
`docker compose down -v` apaga o volume do banco (usuários, análises e histórico).

## Integridade
`SHA256SUMS.txt` traz o hash do `.tar`. No macOS: `shasum -a 256 -c SHA256SUMS.txt`; no Linux: `sha256sum -c SHA256SUMS.txt`;
no Windows: `Get-FileHash @@TAR_NAME@@ -Algorithm SHA256`.
EOF

HASH="$(shasum -a 256 "$TAR_PATH" | awk '{print $1}')"
printf '%s  %s\n' "$HASH" "$TAR_NAME" > "$OUT_DIR/SHA256SUMS.txt"

SIZE_MB=$(( $(wc -c < "$TAR_PATH") / 1048576 ))
echo ""
printf '\033[0;32mPacote pronto em %s/ (%s = %s MB)\033[0m\n' "$OUT_DIR" "$TAR_NAME" "$SIZE_MB"
echo "Copie a pasta inteira para o outro computador e siga o INSTALL.md."
