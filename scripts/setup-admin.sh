#!/bin/bash

# Setup automático para macOS/Linux
# Equivalente a scripts/setup-admin.ps1 para PowerShell
#
# Uso:
#   ./scripts/setup-admin.sh
#   ./scripts/setup-admin.sh --password 'OutraSenha!1' --reset-password
#   ./scripts/setup-admin.sh --no-up --expire-days 365 --token-label "Claude Desktop"
#
# Opções:
#   --login <email>              Email/login do admin (padrão: admin)
#   --password <senha>           Senha do admin (padrão: Senh@123)
#   --compose-file <arquivo>     Arquivo de compose (padrão: docker-compose.local.yml)
#   --env-file <arquivo>         Arquivo .env (padrão: .env)
#   --api-url <url>              URL da API (padrão: http(s)://localhost:3000 conforme .env)
#   --token-label <label>        Label do token (padrão: admin-mcp)
#   --expire-days <dias>         Dias até expirar (0 = sem expiração, padrão: 0)
#   --token-file <arquivo>       Arquivo para salvar token (padrão: secrets/admin-token.txt)
#   --no-up                      Não subi o compose (já está rodando)
#   --skip-token                 Não emite o token
#   --reset-password             Regrava a senha no banco
#   --force-new-fernet-key       Gera nova FERNET_KEY (cuidado!)

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Defaults
LOGIN="admin"
PASSWORD="Senh@123"
DEFAULT_PASSWORD="Senh@123"
FERNET_PLACEHOLDER="sua_chave_fernet_aqui"
NO_UP=false
SKIP_TOKEN=false
RESET_PASSWORD=false
FORCE_NEW_FERNET_KEY=false
COMPOSE_FILE=""
ENV_FILE=".env"
API_URL=""
TOKEN_LABEL="admin-mcp"
EXPIRE_DAYS="0"
TOKEN_FILE="secrets/admin-token.txt"
PROJECT_NAME=""

# -------- Funções --------

write_step() {
    echo -e "${CYAN}==> $1${NC}"
}

write_error() {
    echo -e "${RED}ERROR: $1${NC}" >&2
    exit 1
}

write_warning() {
    echo -e "${YELLOW}WARNING: $1${NC}" >&2
}

write_success() {
    echo -e "${GREEN}$1${NC}"
}

# Gera uma chave Fernet: 32 bytes aleatórios em base64 url-safe (44 chars)
generate_fernet_key() {
    openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n' | head -c 44
}

# Encontra a raiz do projeto (onde está docker-compose.local.yml)
find_project_root() {
    local root="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"  # scripts/
    root=$(dirname "$root")  # raiz

    # Se não tem compose aqui, tenta sair mais um nível (para pacote dist)
    if [[ ! -f "$root/docker-compose.local.yml" ]] && [[ ! -f "$root/docker-compose.yml" ]]; then
        write_error "Não encontrei docker-compose.local.yml ou docker-compose.yml"
    fi

    echo "$root"
}

# Lê variável do .env
read_env_var() {
    local var=$1
    local file=$2
    grep "^${var}=" "$file" 2>/dev/null | cut -d= -f2- | tr -d '"'\'''
}

# Escreve/atualiza variável no .env
update_env_var() {
    local var=$1
    local value=$2
    local file=$3

    if grep -q "^${var}=" "$file"; then
        # Escape special chars para sed
        local escaped_value=$(printf '%s\n' "$value" | sed -e 's/[\/&]/\\&/g')
        sed -i.bak "s/^${var}=.*/${var}=${escaped_value}/" "$file"
        rm -f "${file}.bak"
    else
        echo "${var}=${value}" >> "$file"
    fi
}

# Parse de argumentos
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --login)
                LOGIN="$2"
                shift 2
                ;;
            --password)
                PASSWORD="$2"
                shift 2
                ;;
            --compose-file)
                COMPOSE_FILE="$2"
                shift 2
                ;;
            --env-file)
                ENV_FILE="$2"
                shift 2
                ;;
            --api-url)
                API_URL="$2"
                shift 2
                ;;
            --token-label)
                TOKEN_LABEL="$2"
                shift 2
                ;;
            --expire-days)
                EXPIRE_DAYS="$2"
                shift 2
                ;;
            --token-file)
                TOKEN_FILE="$2"
                shift 2
                ;;
            --project-name)
                PROJECT_NAME="$2"
                shift 2
                ;;
            --no-up)
                NO_UP=true
                shift
                ;;
            --skip-token)
                SKIP_TOKEN=true
                shift
                ;;
            --reset-password)
                RESET_PASSWORD=true
                shift
                ;;
            --force-new-fernet-key)
                FORCE_NEW_FERNET_KEY=true
                shift
                ;;
            *)
                write_error "Opção desconhecida: $1"
                ;;
        esac
    done
}

# -------- Main --------

parse_args "$@"

# Encontra raiz do projeto
ROOT=$(find_project_root)
cd "$ROOT"

# Detecta compose file se não foi especificado
if [[ -z "$COMPOSE_FILE" ]]; then
    if [[ -f "docker-compose.local.yml" ]]; then
        COMPOSE_FILE="docker-compose.local.yml"
    else
        COMPOSE_FILE="docker-compose.yml"
    fi
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
    write_error "Arquivo compose não encontrado: $COMPOSE_FILE"
fi

# -------- 1) .env + FERNET_KEY --------
write_step "[1/5] Chave FERNET em $ENV_FILE"

if [[ ! -f "$ENV_FILE" ]]; then
    if [[ ! -f ".env.example" ]]; then
        write_error "$ENV_FILE não existe e não há .env.example para copiar"
    fi
    cp .env.example "$ENV_FILE"
    echo "    $ENV_FILE criado a partir do .env.example"
fi

# Lê FERNET_KEY atual
CURRENT_FERNET=$(read_env_var "FERNET_KEY" "$ENV_FILE" || true)

if [[ "$FORCE_NEW_FERNET_KEY" == true ]] || [[ -z "$CURRENT_FERNET" ]] || [[ "$CURRENT_FERNET" == "$FERNET_PLACEHOLDER" ]]; then
    if [[ "$FORCE_NEW_FERNET_KEY" == true ]] && [[ -n "$CURRENT_FERNET" ]] && [[ "$CURRENT_FERNET" != "$FERNET_PLACEHOLDER" ]]; then
        write_warning "Trocando uma FERNET_KEY existente: as senhas de data source já gravadas ficam ilegíveis até serem recifradas."
    fi

    NEW_FERNET=$(generate_fernet_key)
    update_env_var "FERNET_KEY" "$NEW_FERNET" "$ENV_FILE"
    echo "    FERNET_KEY gerada e gravada em $ENV_FILE"
else
    # Valida formato (44 caracteres, base64 url-safe)
    if ! [[ "$CURRENT_FERNET" =~ ^[A-Za-z0-9_-]{43}=?$ ]]; then
        write_warning "FERNET_KEY existente não parece válida (esperado 44 caracteres base64 url-safe)"
    fi
    echo "    FERNET_KEY já definida: mantida"
fi

# Verifica POSTGRES_CONFIG_PASSWORD
if grep -q "^POSTGRES_CONFIG_PASSWORD=changeme" "$ENV_FILE"; then
    write_warning "POSTGRES_CONFIG_PASSWORD ainda é 'changeme'. Troque no $ENV_FILE antes de criar o banco."
fi

# -------- Prepara docker compose command --------
DOCKER_CMD="docker compose"
if [[ -n "$PROJECT_NAME" ]]; then
    DOCKER_CMD="$DOCKER_CMD -p $PROJECT_NAME"
fi
DOCKER_CMD="$DOCKER_CMD -f $COMPOSE_FILE --env-file $ENV_FILE"

# -------- Detecta API URL --------
if [[ -z "$API_URL" ]]; then
    PORT=$(read_env_var "SERVER_PORT" "$ENV_FILE" || echo "3000")

    if grep -q "^TLS_ENABLED=false" "$ENV_FILE"; then
        SCHEME="http"
    else
        SCHEME="https"
    fi

    API_URL="${SCHEME}://localhost:${PORT}"
fi

# Remove trailing slash
API_URL="${API_URL%/}"

# -------- 2) Subir docker compose --------
if [[ "$NO_UP" == true ]]; then
    write_step "[2/5] docker compose up -d: pulado (--no-up)"
else
    write_step "[2/5] docker compose up -d (o seed do admin roda sozinho se o banco for criado agora)"
    eval "$DOCKER_CMD up -d" || write_error "Falha ao subir docker compose"
fi

# -------- 3) Health check --------
write_step "[3/5] Aguardando ${API_URL}/health"

TIMEOUT=120
START_TIME=$(date +%s)

while true; do
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))

    if [[ $ELAPSED -gt $TIMEOUT ]]; then
        write_error "O app não respondeu 'ok' em ${TIMEOUT}s. Veja: $DOCKER_CMD logs app"
    fi

    # Tenta curl com timeout, ignorando erros de certificado para localhost
    if HEALTH=$(curl -s -m 5 -k "${API_URL}/health" 2>/dev/null); then
        if echo "$HEALTH" | grep -q '"status":"ok"'; then
            echo "    app e banco no ar"
            break
        fi
    fi

    sleep 2
done

# -------- 4) Executar seed (idempotente) --------
write_step "[4/5] Administrador '$LOGIN' (usuário + perfil admin + vínculos)"

RESET_FLAG="0"
if [[ "$RESET_PASSWORD" == true ]]; then
    RESET_FLAG="1"
fi

eval "$DOCKER_CMD exec -T -e ADMIN_LOGIN=$LOGIN -e ADMIN_PASSWORD=$PASSWORD -e ADMIN_RESET_PASSWORD=$RESET_FLAG postgres sh /docker-entrypoint-initdb.d/02-seed-admin.sh" \
    || write_error "Falha ao executar o seed. Se o banco foi criado antes desta versão, rode sem --no-up."

if [[ "$RESET_PASSWORD" == true ]]; then
    echo "    senha do admin regravada (--reset-password)"
fi

# -------- 5) Emitir token --------
if [[ "$SKIP_TOKEN" == true ]]; then
    write_step "[5/5] Token: pulado (--skip-token)"
    exit 0
fi

write_step "[5/5] Token de acesso (POST /auth/token)"

# Prepara JSON body
BODY=$(cat <<EOF
{
  "email": "$LOGIN",
  "password": "$PASSWORD",
  "label": "$TOKEN_LABEL"
EOF
)

if [[ "$EXPIRE_DAYS" != "0" ]] && [[ "$EXPIRE_DAYS" != "0" ]]; then
    BODY="${BODY},
  \"expire_days\": $EXPIRE_DAYS"
fi

BODY="${BODY}
}"

# Faz POST para /auth/token (ignora erro de certificado para localhost)
RESPONSE=$(curl -s -X POST -k "${API_URL}/auth/token" \
    -H "Content-Type: application/json" \
    -d "$BODY")

# Verifica se foi erro 401
if echo "$RESPONSE" | grep -q '"error_code":"INVALID_CREDENTIALS"'; then
    write_error "401: login ou senha não conferem. Se o admin '$LOGIN' já existia com outra senha, rode de novo com --reset-password."
fi

# Verifica se tem 'error' na resposta
if echo "$RESPONSE" | grep -q '"error'; then
    write_error "Falha ao emitir o token: $RESPONSE"
fi

# Extrai token (com jq se disponível, senão com grep/sed)
if command -v jq &> /dev/null; then
    TOKEN=$(echo "$RESPONSE" | jq -r '.token')
    EXPIRES_AT=$(echo "$RESPONSE" | jq -r '.expires_at')
else
    TOKEN=$(echo "$RESPONSE" | grep -o '"token":"[^"]*' | cut -d'"' -f4)
    EXPIRES_AT=$(echo "$RESPONSE" | grep -o '"expires_at":"[^"]*' | cut -d'"' -f4)
fi

if [[ -z "$TOKEN" ]]; then
    write_error "Não consegui extrair o token da resposta: $RESPONSE"
fi

# Salva token em arquivo
mkdir -p "$(dirname "$TOKEN_FILE")"
echo -n "$TOKEN" > "$TOKEN_FILE"

# Output final
echo ""
write_success "Pronto."
echo "  Login:      $LOGIN"
echo "  Token:      $TOKEN"
echo "  Expira em:  $EXPIRES_AT"
echo "  Salvo em:   $TOKEN_FILE   (fora do git; o token NÃO pode ser recuperado depois)"
echo ""
echo "Cliente MCP (Claude Desktop com mcp-remote):"
cat <<EOF
"analise-dados": {
  "command": "npx",
  "args": ["mcp-remote", "${API_URL}/mcp", "--header", "Authorization:\${AUTH_HEADER}"],
  "env": {"NODE_OPTIONS": "--use-system-ca", "AUTH_HEADER": "Bearer $TOKEN"}
}
EOF

# Avisa se usando senha padrão
if [[ "$PASSWORD" == "$DEFAULT_PASSWORD" ]]; then
    echo ""
    write_warning "A senha do admin é a PADRÃO e é conhecida. Troque com: ./scripts/setup-admin.sh --no-up --password 'nova' --reset-password"
fi
