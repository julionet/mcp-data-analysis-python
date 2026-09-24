# 🚀 Roteiro de Inicialização do Ambiente de Desenvolvimento

## Plataforma de Análise de Dados Genérica com MCP (V1.0)

> Baseado em: `ARQUITETURA.md` §5 (Stack Técnico), §7 (ADR-006) e §9 (Plano de Implantação), `NEGOCIO.md` §8 (RNF5) e §9 (Restrições T1-T4).
> Este roteiro cobre apenas a preparação do ambiente — **antes** de iniciar a implementação das Feature Specs (F1 em diante).
> Atualizado após o protótipo F0 (`F0_PROTOTIPO_MCP_MEMORIA.md`, ver `mcp_prototype/README.md`): TLS local passou a ser um pré-requisito de ambiente, não só um detalhe de deploy remoto.

---

## 1. Pré-requisitos de Sistema

```bash
# Verificar versões
python3 --version   # precisa ser 3.11+ (Restrição T2, ARQUITETURA.md §5.1)
# Python 3.12.14
docker --version
# Docker version 29.8.0, build 88096ef
docker compose version
# Docker version 29.8.0, build 88096ef
git --version
# git version 2.54.0 (Apple Git-157)
psql --version       # PostgreSQL 13+ client (ARQUITETURA.md §10)
# postgres (PostgreSQL) 18.6 (Homebrew)
mkcert -version      # gera certificado TLS local confiável (ver seção 2) — instalar com `brew install mkcert` se ausente
# v1.4.4
```

> ⚠️ **SQL Server (F13):** o driver ODBC nativo da Microsoft (`msodbcsql17`/`18`) é dependência de SO, não `pip`. Só entra no `Dockerfile` na **F15 (Docker Setup, Sprint 3)** — não é necessário instalar agora para o Sprint 1.

---

## 2. Certificado TLS Local (mkcert)

TLS é obrigatório mesmo em rede interna e mesmo em desenvolvimento local (ver ARQUITETURA.md §7 ADR-006) — clientes MCP reais (confirmado: Claude Desktop) recusam se conectar a um conector remoto via `http://` simples, independente da rede ser confiável.

```bash
brew install mkcert
mkcert -install          # instala a CA local no Keychain do macOS (pede senha uma vez)

mkdir -p certs
cd certs
mkcert localhost 127.0.0.1 <ip-da-maquina>
cd ..
```

Isso gera `certs/localhost+2.pem` e `certs/localhost+2-key.pem` — **nunca versionar a chave privada** (adicionar `certs/` ao `.gitignore`).

> ⚠️ **ALPN:** subir o servidor apenas com `uvicorn --ssl-certfile=... --ssl-keyfile=...` pela CLI não basta — ela não negocia ALPN, e alguns clientes (Chromium/Electron) abandonam a conexão TLS sem nunca enviar uma requisição HTTP. É necessário um `ssl_context_factory` programático chamando `context.set_alpn_protocols(["http/1.1"])` (ver `mcp_prototype/run_https.py` para um exemplo funcional).

> Se algum cliente estiver em outra máquina da rede, gere o certificado também para o IP/hostname do servidor e instale a mesma CA (`mkcert -CAROOT`) na máquina do cliente antes de confiar nele.

---

## 3. Estrutura de Diretórios

Conforme `ARQUITETURA.md` §5.2:

```bash
mkdir -p analysis_app/{adapters,handlers/built_in,handlers/custom,services,repositories,schemas,mcp,database/migrations/versions,logs,tests}
cd analysis_app

touch main.py config.py requirements.txt .env.example
touch docker-compose.local.yml docker-compose.remote.yml

for d in adapters handlers handlers/built_in handlers/custom services repositories schemas mcp database tests; do
  touch "$d/__init__.py"
done
```

---

## 4. Ambiente Virtual + Dependências

```bash
python3.11 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

**Dependências completas** (`requirements.txt`) conforme `ARQUITETURA.md` §5.1: `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `mcp`, `asyncpg`, `motor`, `aiomysql`, `aioodbc` + `pyodbc`, `sqlalchemy`, `alembic`, `pandas`, `numpy`, `redis`, `aioredis`, `celery`, `marshmallow`, `python-json-logger`, `structlog`, `python-dotenv`, `uuid6`.

**Estritamente necessário para o Sprint 1 (F1-F8):**

```
fastapi
uvicorn[standard]
pydantic
pydantic-settings
mcp>=1.9.0,<2.0.0   # teto obrigatório: a v2.0.0 remove os decorators list_tools()/call_tool()
                     # da classe de baixo nível Server (ver ARQUITETURA.md §7 ADR-006)
asyncpg
sqlalchemy
alembic
python-dotenv
structlog
```

> Os demais (`motor`, `aiomysql`, `aioodbc`/`pyodbc`, `celery`, `redis`) entram conforme as sprints seguintes: MongoDB/MySQL/SQL Server no Sprint 2 (F11-F13), Celery/Redis no Sprint 3 (F15+, ambiente remoto).
>
> ⚠️ Não fixar `fastapi`/`uvicorn[standard]` numa versão exata antiga junto de `mcp` — no protótipo F0 isso gerou `ResolutionImpossible` (as dependências transitivas do `mcp` exigem versões mais recentes). Deixe o `pip` resolver a versão compatível e trave só o `mcp`.

---

## 5. PostgreSQL — Banco de Configuração

Restrição T3 (`NEGOCIO.md` §9): banco de config **separado** do(s) banco(s) de negócio (data sources).

```bash
# Local via Docker
docker run -d --name pg-config \
  -e POSTGRES_DB=analysis_config \
  -e POSTGRES_PASSWORD=<senha> \
  -p 5432:5432 postgres:15

# Aplicar o schema (ARQUITETURA.md §2.2)
psql -h localhost -U postgres -d analysis_config -f database/schema.sql
```

Extrair o SQL de `ARQUITETURA.md` §2.2 para `database/schema.sql`:

- `data_sources`
- `analyses`
- `analysis_steps`
- `analysis_versions`
- `custom_handlers`
- `execution_history`
- índices (`idx_analyses_active`, `idx_execution_history_analysis`, etc.)

Alternativa: criar via Alembic desde já —

```bash
alembic init database/migrations
# primeira revision cobrindo as 6 tabelas na ordem do schema
```

---

## 6. Arquivo `.env`

Conforme `ARQUITETURA.md` §8.2:

```env
POSTGRES_CONFIG_HOST=localhost
POSTGRES_CONFIG_PORT=5432
POSTGRES_CONFIG_DB=analysis_config
POSTGRES_CONFIG_USER=postgres
POSTGRES_CONFIG_PASSWORD=changeme

MCP_SERVER_PORT=3000
MCP_SERVER_HOST=0.0.0.0

# TLS obrigatório mesmo em V1.0 (ver ARQUITETURA.md §7 ADR-006) — gerado na seção 2
MCP_SSL_CERTFILE=certs/localhost+2.pem
MCP_SSL_KEYFILE=certs/localhost+2-key.pem

# Sem chaves de API / autenticação — fora de escopo em V1.0 (Restrição T5)
```

---

## 7. Docker Compose Local (mínimo do Sprint 1)

```yaml
# docker-compose.local.yml
services:
  postgres_config:
    image: postgres:15
    environment:
      POSTGRES_DB: analysis_config
      POSTGRES_PASSWORD: ${POSTGRES_CONFIG_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data

volumes:
  pg_data:
```

> O app FastAPI/uvicorn **não** entra no compose ainda. Mais simples rodar o servidor direto (com TLS + ALPN configurados programaticamente, ver seção 2) durante o desenvolvimento de F1-F8, e containerizar a aplicação só na **F15 (Docker Setup, Sprint 3)**.

---

## 8. Controle de Versão

Conforme workflow SDD (`FEATURES_ROADMAP.md` §5):

```bash
git init
git checkout -b feature/F1-fastapi-mcp-setup
```

> Adicionar `certs/` ao `.gitignore` antes do primeiro commit — nunca versionar a chave privada do certificado TLS gerada na seção 2.

---

## 9. Configuração do Claude Desktop

Para conectar o Claude Desktop ao servidor MCP local, edite o arquivo de configuração:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Adicione a entrada abaixo em `mcpServers`:

```json
{
  "mcpServers": {
    "analise-dados": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://127.0.0.1:3000/mcp"
      ],
      "env": {
        "NODE_OPTIONS": "--use-system-ca"
      }
    }
  }
}
```

> `NODE_OPTIONS=--use-system-ca` faz o Node.js (usado pelo `mcp-remote`) confiar na CA do sistema onde o `mkcert -install` foi executado na seção 2 — sem isso ele rejeita o certificado TLS local com `UNABLE_TO_VERIFY_LEAF_SIGNATURE`.

> Após salvar, **reiniciar o Claude Desktop** para que ele recarregue os servidores MCP. O servidor local deve estar no ar (`python main.py` ou equivalente) antes de abrir o Claude.

---

## 10. Verificação Final

```bash
docker compose -f docker-compose.local.yml up -d
psql -h localhost -U postgres -d analysis_config -c "\dt"   # confirma as 6 tabelas
curl https://localhost:3000/health                          # confirma TLS servindo sem aviso de certificado
```

**Checklist antes de codar** (`FEATURES_ROADMAP.md` §4):

- [x] Python 3.11+ confirmado
- [x] PostgreSQL acessível na rede local
- [ ] Certificado TLS local gerado e CA confiável instalada (mkcert)
- [x] Estrutura de diretórios criada
- [x] `requirements.txt` (mínimo Sprint 1) instalado
- [x] `.env` configurado (incluindo caminhos do certificado TLS)
- [ ] Schema aplicado (6 tabelas visíveis via `\dt`)
- [x] Branch `feature/F1-fastapi-mcp-setup` criada

---

## 11. Troubleshooting

- **Porta 3000 já em uso** (`address already in use` ao subir o servidor): identificar e encerrar o processo antigo antes de subir um novo —
  ```bash
  lsof -nP -iTCP:3000 -sTCP:LISTEN
  kill <PID>
  ```
- **Cliente MCP reporta "nenhum servidor respondeu" mesmo com o servidor no ar:** verificar, nesta ordem, os pontos que o protótipo F0 já cobriu — certificado confiável (`curl -v https://.../health`), negociação ALPN (`openssl s_client -alpn h2,http/1.1 -connect 127.0.0.1:3000`), e CORS habilitado. Detalhes completos em `mcp_prototype/README.md`.

---

## Próximo Passo

Com o ambiente pronto, iniciar a **Feature Spec de F1** (FastAPI + MCP Server Setup via Streamable HTTP, com TLS), seguindo o template de `FEATURES_ROADMAP.md` §2.
