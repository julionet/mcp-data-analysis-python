#!/usr/bin/env bash
# Prepara o ambiente no macOS/Linux: chave FERNET no .env, administrador (usuário + perfil + vínculo)
# e token MCP. Equivalente a scripts/setup-admin.ps1, com as mesmas etapas e opções (--kebab-case).
#
# Uso (raiz do repositório ou pasta do pacote dist):
#   ./scripts/setup-admin.sh
#   ./scripts/setup-admin.sh --no-up --password 'OutraSenha!1' --reset-password
#   ./scripts/setup-admin.sh --no-up --expire-days 365 --token-label "Claude Desktop"
#
# Opções: --help para a lista completa.

set -euo pipefail

DEFAULT_PASSWORD="Senh@123"
FERNET_PLACEHOLDER="sua_chave_fernet_aqui"

LOGIN="admin"
PASSWORD="$DEFAULT_PASSWORD"
COMPOSE_FILE=""
PROJECT_NAME=""
ENV_FILE=".env"
API_URL=""
TOKEN_LABEL="admin-mcp"
EXPIRE_DAYS=0
TOKEN_FILE="secrets/admin-token.txt"
NO_UP=false
SKIP_TOKEN=false
RESET_PASSWORD=false
FORCE_NEW_FERNET_KEY=false

usage() {
    cat <<'EOF'
Uso: ./scripts/setup-admin.sh [opções]

  --login <email>            login do admin (padrão: admin)
  --password <senha>         senha do admin (padrão: Senh@123, conhecida: troque fora do desenvolvimento)
  --reset-password           regrava a senha de um admin que já existe
  --no-up                    não roda 'docker compose up -d' (containers já estão no ar)
  --skip-token               não emite o token
  --expire-days <n>          validade do token em dias (0 = padrão do servidor)
  --token-label <texto>      rótulo do token (padrão: admin-mcp)
  --token-file <arquivo>     onde salvar o token (padrão: secrets/admin-token.txt)
  --compose-file <arquivo>   compose (padrão: docker-compose.local.yml; no pacote dist, docker-compose.yml)
  --env-file <arquivo>       arquivo de variáveis (padrão: .env)
  --api-url <url>            URL da API (padrão: http(s)://localhost:<SERVER_PORT> conforme o .env)
  --project-name <nome>      nome do projeto do compose (docker compose -p)
  --force-new-fernet-key     gera nova FERNET_KEY (torna ilegíveis os data sources já gravados)
  -h, --help                 mostra esta ajuda
EOF
}

die() {
    printf '\033[0;31mERRO: %s\033[0m\n' "$1" >&2
    exit 1
}

step() {
    printf '\033[0;36m==> %s\033[0m\n' "$1"
}

warn() {
    printf '\033[1;33mAVISO: %s\033[0m\n' "$1" >&2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --reset-password) RESET_PASSWORD=true; shift ;;
        --no-up) NO_UP=true; shift ;;
        --skip-token) SKIP_TOKEN=true; shift ;;
        --force-new-fernet-key) FORCE_NEW_FERNET_KEY=true; shift ;;
        --login|--password|--expire-days|--token-label|--token-file|--compose-file|--env-file|--api-url|--project-name)
            [[ $# -ge 2 ]] || die "a opção $1 precisa de um valor"
            case "$1" in
                --login) LOGIN="$2" ;;
                --password) PASSWORD="$2" ;;
                --expire-days) EXPIRE_DAYS="$2" ;;
                --token-label) TOKEN_LABEL="$2" ;;
                --token-file) TOKEN_FILE="$2" ;;
                --compose-file) COMPOSE_FILE="$2" ;;
                --env-file) ENV_FILE="$2" ;;
                --api-url) API_URL="$2" ;;
                --project-name) PROJECT_NAME="$2" ;;
            esac
            shift 2
            ;;
        *) die "opção desconhecida: $1 (use --help)" ;;
    esac
done

[[ "$EXPIRE_DAYS" =~ ^[0-9]+$ ]] || die "--expire-days precisa ser um número inteiro"

# Raiz do projeto: a pasta do script se ela tem um compose (pacote dist); senão, a pasta acima (repositório).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if compgen -G "$SCRIPT_DIR/docker-compose*.yml" >/dev/null; then
    ROOT="$SCRIPT_DIR"
    SELF_HINT="./setup-admin.sh"
else
    ROOT="$(dirname "$SCRIPT_DIR")"
    SELF_HINT="./scripts/setup-admin.sh"
fi
cd "$ROOT"

if [[ -z "$COMPOSE_FILE" ]]; then
    if [[ -f docker-compose.local.yml ]]; then COMPOSE_FILE="docker-compose.local.yml"; else COMPOSE_FILE="docker-compose.yml"; fi
fi
[[ -f "$COMPOSE_FILE" ]] || die "compose não encontrado: $COMPOSE_FILE (rodando em $ROOT)"

# Lê a última ocorrência de CHAVE=valor no arquivo (vazio se não existir).
env_get() {
    local line
    line=$(grep -E "^$2=" "$1" 2>/dev/null | tail -n 1) || true
    printf '%s' "${line#*=}" | tr -d '\r'
}

# Grava CHAVE=valor: substitui a linha existente ou acrescenta no fim. Sem BOM, com LF.
env_set() {
    local file="$1" key="$2" value="$3" tmp
    tmp="$(mktemp)"
    if grep -q -E "^$key=" "$file"; then
        awk -v k="$key" -v v="$value" 'index($0, k "=") == 1 { print k "=" v; next } { print }' "$file" > "$tmp"
    else
        cat "$file" > "$tmp"
        if [[ -s "$tmp" && -n "$(tail -c 1 "$tmp")" ]]; then printf '\n' >> "$tmp"; fi
        printf '%s=%s\n' "$key" "$value" >> "$tmp"
    fi
    cat "$tmp" > "$file"
    rm -f "$tmp"
}

# Chave Fernet: 32 bytes aleatórios em base64 url-safe (44 caracteres, com o '=' final).
new_fernet_key() {
    openssl rand -base64 32 | tr -d '\n' | tr '+/' '-_'
}

# Escapa aspas e barras para inserir o valor dentro de uma string JSON.
json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

# ---- 1) .env + FERNET_KEY ---------------------------------------------------------------------
step "[1/5] Chave FERNET em $ENV_FILE"
if [[ ! -f "$ENV_FILE" ]]; then
    [[ -f .env.example ]] || die "$ENV_FILE não existe e não há .env.example para copiar"
    cp .env.example "$ENV_FILE"
    echo "    $ENV_FILE criado a partir do .env.example"
fi

CURRENT_FERNET="$(env_get "$ENV_FILE" FERNET_KEY)"
if [[ "$FORCE_NEW_FERNET_KEY" == true || -z "$CURRENT_FERNET" || "$CURRENT_FERNET" == "$FERNET_PLACEHOLDER" ]]; then
    if [[ "$FORCE_NEW_FERNET_KEY" == true && -n "$CURRENT_FERNET" && "$CURRENT_FERNET" != "$FERNET_PLACEHOLDER" ]]; then
        warn "Trocando uma FERNET_KEY existente: as senhas de data source já gravadas ficam ilegíveis até serem recifradas."
    fi
    env_set "$ENV_FILE" FERNET_KEY "$(new_fernet_key)"
    echo "    FERNET_KEY gerada e gravada em $ENV_FILE"
else
    if ! [[ "$CURRENT_FERNET" =~ ^[A-Za-z0-9_-]{43}=$ ]]; then
        warn "FERNET_KEY existente não parece uma chave Fernet válida (44 caracteres base64 url-safe)."
    fi
    echo "    FERNET_KEY já definida: mantida"
fi

if grep -q -E '^POSTGRES_CONFIG_PASSWORD=changeme[[:space:]]*$' "$ENV_FILE"; then
    warn "POSTGRES_CONFIG_PASSWORD ainda é 'changeme'. Em banco novo ela vira a senha do Postgres; troque no $ENV_FILE antes de criar o banco."
fi

# ---- docker compose ---------------------------------------------------------------------------
DC=(docker compose)
if [[ -n "$PROJECT_NAME" ]]; then DC+=(-p "$PROJECT_NAME"); fi
DC+=(-f "$COMPOSE_FILE" --env-file "$ENV_FILE")

docker info >/dev/null 2>&1 || die "o Docker não está rodando. Abra o Docker Desktop e tente de novo."

# URL da API: porta e TLS vêm do .env
if [[ -z "$API_URL" ]]; then
    PORT="$(env_get "$ENV_FILE" SERVER_PORT)"
    PORT="${PORT:-3000}"
    if [[ "$(env_get "$ENV_FILE" TLS_ENABLED)" == "false" ]]; then SCHEME="http"; else SCHEME="https"; fi
    API_URL="${SCHEME}://localhost:${PORT}"
fi
API_URL="${API_URL%/}"

# Certificado mkcert não é confiado por padrão: só ignoramos a validação para localhost.
CURL_K=""
case "$API_URL" in
    http://localhost*|https://localhost*|http://127.0.0.1*|https://127.0.0.1*) CURL_K="-k" ;;
esac

# ---- 2) subir ---------------------------------------------------------------------------------
if [[ "$NO_UP" == true ]]; then
    step "[2/5] docker compose up -d: pulado (--no-up)"
else
    step "[2/5] docker compose up -d (o seed do admin roda sozinho se o banco for criado agora)"
    "${DC[@]}" up -d || die "falha ao subir o compose"
fi

# ---- 3) health --------------------------------------------------------------------------------
step "[3/5] Aguardando $API_URL/health"
DEADLINE=$(( $(date +%s) + 120 ))
HEALTH=""
until [[ "$HEALTH" == *'"status":"ok"'* ]]; do
    if (( $(date +%s) >= DEADLINE )); then
        die "o app não respondeu 'ok' em $API_URL/health em 120 s. Veja: ${DC[*]} logs app"
    fi
    HEALTH="$(curl -fsS -m 5 $CURL_K "$API_URL/health" 2>/dev/null || true)"
    [[ "$HEALTH" == *'"status":"ok"'* ]] || sleep 2
done
echo "    app e banco no ar"

# ---- 4) seed (idempotente) --------------------------------------------------------------------
step "[4/5] Administrador '$LOGIN' (usuário + perfil admin + vínculos)"
RESET_FLAG=0
if [[ "$RESET_PASSWORD" == true ]]; then RESET_FLAG=1; fi
"${DC[@]}" exec -T \
    -e "ADMIN_LOGIN=$LOGIN" -e "ADMIN_PASSWORD=$PASSWORD" -e "ADMIN_RESET_PASSWORD=$RESET_FLAG" \
    postgres sh /docker-entrypoint-initdb.d/02-seed-admin.sh \
    || die "falha ao executar o seed no container postgres. Se o banco foi criado antes deste seed, rode sem --no-up (o 'up -d' recria o postgres com o volume preservado)."
if [[ "$RESET_PASSWORD" == true ]]; then echo "    senha do admin regravada (--reset-password)"; fi

# ---- 5) token ---------------------------------------------------------------------------------
if [[ "$SKIP_TOKEN" == true ]]; then
    step "[5/5] Token: pulado (--skip-token)"
    exit 0
fi

step "[5/5] Token de acesso (POST /auth/token)"
BODY="{\"email\":\"$(json_escape "$LOGIN")\",\"password\":\"$(json_escape "$PASSWORD")\",\"label\":\"$(json_escape "$TOKEN_LABEL")\""
if (( EXPIRE_DAYS > 0 )); then BODY+=",\"expire_days\":$EXPIRE_DAYS"; fi
BODY+="}"

RESP_FILE="$(mktemp)"
trap 'rm -f "$RESP_FILE"' EXIT
HTTP_CODE="$(curl -sS -m 30 $CURL_K -o "$RESP_FILE" -w '%{http_code}' -X POST "$API_URL/auth/token" \
    -H 'Content-Type: application/json' -d "$BODY")" \
    || die "não consegui conectar em $API_URL/auth/token"
RESP="$(cat "$RESP_FILE")"

case "$HTTP_CODE" in
    200) ;;
    401) die "401: login ou senha não conferem. Se o admin '$LOGIN' já existia com outra senha, rode de novo com --reset-password." ;;
    *) die "falha ao emitir o token (HTTP $HTTP_CODE): $RESP" ;;
esac

TOKEN="$(printf '%s' "$RESP" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')"
EXPIRES_AT="$(printf '%s' "$RESP" | sed -n 's/.*"expires_at":"\([^"]*\)".*/\1/p')"
[[ -n "$TOKEN" ]] || die "resposta sem token: $RESP"

mkdir -p "$(dirname "$TOKEN_FILE")"
printf '%s\n' "$TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"

MCP_URL="$API_URL/mcp"
echo ""
printf '\033[0;32mPronto.\033[0m\n'
echo "  Login:      $LOGIN"
echo "  Token:      $TOKEN"
echo "  Expira em:  $EXPIRES_AT"
echo "  Salvo em:   $TOKEN_FILE   (fora do git; o token NÃO pode ser recuperado depois)"
echo ""
echo "Cliente MCP (Claude Desktop com mcp-remote):"
cat <<EOF
"analise-dados": {
  "command": "npx",
  "args": ["mcp-remote", "$MCP_URL", "--header", "Authorization:\${AUTH_HEADER}"],
  "env": {"NODE_OPTIONS": "--use-system-ca", "AUTH_HEADER": "Bearer $TOKEN"}
}
EOF

if [[ "$PASSWORD" == "$DEFAULT_PASSWORD" ]]; then
    echo ""
    warn "a senha do admin é a PADRÃO e é conhecida. Troque com: $SELF_HINT --no-up --password 'nova' --reset-password"
fi
