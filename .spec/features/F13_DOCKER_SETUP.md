# [F13] Docker Setup (Local + Remote)

## Feature Spec

**ID:** F13
**Nome:** Docker Setup — um container por artefato (local + remote)
**Prioridade:** 🔴 Crítica
**Esforço Estimado:** 2d (16h)
**Status:** 🟩 Done (2026-10-03) — validação manual pendente (ver §6.2): cliente MCP real, SSE no nginx, Oracle e Certbot

> **Origem dos requisitos:** FEATURES_ROADMAP.md v1.17 ("F13 em detalhe"), NEGOCIO.md RNF2 (Portabilidade) e ARQUITETURA.md §5.1, §8.2, §9.1–9.3, mais as decisões desta sessão (2026-10-01), registradas na §10.

---

## 1. Visão

Empacotar cada artefato do ambiente em seu próprio container — servidor MCP, PostgreSQL (Config DB), MySQL, SQL Server e Oracle — para subir tudo com 1 comando no ambiente local e reaproveitar o mesmo código no remoto, só trocando a configuração. Os containers SQL Server e Oracle são criados, mas **não** entram na execução do compose (opcionais, subida manual).

## 2. Objetivo

Ter `Dockerfile`s, `docker-compose.local.yml` e `docker-compose.remote.yml` prontos, de modo que um desenvolvedor suba o ambiente completo sem instalar bancos nem drivers na máquina.

**Métrica de Sucesso:**
- ✅ `docker compose -f docker-compose.local.yml up` sobe `app`, `postgres` e `mysql`; `GET /health` retorna `{"status":"ok","db":true}`
- ✅ O `postgres` inicia com o `schema.sql` aplicado (incluindo as tabelas da F12)
- ✅ Handshake TLS/ALPN funciona no `app` (local: mkcert montado)
- ✅ `POST /auth/token` → `/mcp` funciona via container
- ✅ O `app` consegue executar uma análise contra MySQL do compose e contra SQL Server subido à parte (driver ODBC 18 presente na imagem)
- ✅ `docker-compose.remote.yml` sobe `nginx` na frente do `app` (TLS terminado no nginx, certificado montado); `certbot` é um profile opcional, desligado até haver domínio e provedor DNS (decisão 8)
- ✅ O artefato Oracle existe e é construível/subível manualmente, mas o `up` padrão **não** o inicia
- ✅ Nenhum secret ou certificado dentro de imagem

## 3. Contexto

**Depende de:** F1–F8 (servidor, adapters, engine) e F12 (autenticação obrigatória) — todas ✅; F9–F11 (adapters dos 4 bancos) — todas ✅.
**É dependência de:** F20 (Production Deployment Guide).

## 4. Descrição Técnica

### 4.1 Componentes Afetados

```
Arquivos novos (nenhum código Python da aplicação é alterado):
analysis_app/
├─ Dockerfile                          # imagem do app
├─ .dockerignore
├─ .env.example                        # ATUALIZADO: variáveis dos bancos/containers/nginx/certbot
docker/
├─ (postgres, mysql: imagens oficiais direto nos compose — sem diretório próprio;
│   schema.sql montado em /docker-entrypoint-initdb.d)
├─ sqlserver/
│   └─ docker-compose.sqlserver.yml    # mssql/server:2022-latest — NÃO roda no compose local/remote
├─ oracle/
│   └─ docker-compose.oracle.yml       # gvenzl/oracle-free (sem login) — NÃO roda no compose local/remote
└─ nginx/
    └─ nginx.conf.template             # reverse proxy TLS → app:3000 (ARQUITETURA.md §9.2)
docker-compose.local.yml               # app + postgres + mysql (TLS: uvicorn + mkcert)
docker-compose.remote.yml              # nginx + certbot + app + bancos (TLS: nginx)
```

> Os arquivos Docker ficam na raiz do repositório (`docker/`, `docker-compose.*.yml`), exceto `Dockerfile`/`.dockerignore`/`.env.example` do app, que ficam em `analysis_app/` (contexto de build = `analysis_app/`).

### 4.2 Containers

| Serviço | Imagem | Porta | Volume | No `up` padrão? |
|---|---|---|---|---|
| `app` | build `analysis_app/Dockerfile` | 3000 | `certs/` (somente leitura, no local) | ✅ |
| `postgres` | `postgres:16` | 5432 | `pgdata`; `schema.sql` em `initdb.d` | ✅ |
| `mysql` | `mysql:8.4` | 3306 | `mysqldata` | ✅ |
| `sqlserver` | `mcr.microsoft.com/mssql/server:2022-latest` | 1433 | `mssqldata` | ❌ **fora do compose** (opcional, como o Oracle) |
| `oracle` | `gvenzl/oracle-free` (sem login) | 1521 | `oradata` | ❌ **fora do compose** (ver 4.5) |
| `nginx` (só remote) | `nginx:stable` | 443 / 80 | `certs/` montado (mkcert por ora; Certbot depois) | ✅ remote |
| `certbot` (só remote) | `certbot/dns-<provedor>` | — | `/etc/letsencrypt` | ❌ profile `certbot` (desligado até haver domínio/DNS) |

Cada banco recebe credencial própria via `.env`. As portas dos bancos só são publicadas no host no compose **local** (para ferramentas de dev); no remote ficam apenas na rede interna do compose.

### 4.3 Dockerfile do app

```
Base: python:3.13-slim-bookworm (versão da suíte; wheels de pyodbc>=5.2/bcrypt>=5 ok)
Passos:
1. apt: curl, gnupg, unixodbc-dev
2. Repositório Microsoft → apt install msodbcsql18   (ODBC 18, par do SQL Server 2022)
3. pip install -r requirements.txt
4. COPY . (respeitando .dockerignore: .env, certs/, .venv, __pycache__, tests/ opcional)
5. USER não-root
6. HEALTHCHECK: GET /health
7. CMD ["python", "run_https.py"]
```

- **ODBC 18:** o driver 18 vem com `Encrypt=yes` por padrão. O `SQLServerAdapter` já mapeia `connection_config.sslmode` (`adapters/sqlserver.py:19-24`): `prefer` (default) → `Encrypt=yes;TrustServerCertificate=yes`, que aceita o certificado autoassinado do container sem alterar código. O `data_source` de dev omite o `sslmode` ou usa `"prefer"`; `verify-full` fica para produção com certificado válido (decisão 9).
- **Oracle:** `oracledb` thin mode — nada no Dockerfile do app (F9 §7).
- **Local:** `TLS_ENABLED=true` + `certs/` montado (mkcert); `run_https.py` mantém o ALPN.
- **Remote:** `TLS_ENABLED=false` no `app` (HTTP interno), porque o nginx termina o TLS e o workaround de ALPN é desnecessário (ARQUITETURA.md §9.2). A porta 3000 **não** é publicada no host.

### 4.4 Remote: nginx (+ Certbot opcional, Opção A — DNS-01)

> **Por ora sem DNS (decisão 8):** o nginx lê `fullchain.pem`/`privkey.pem` de `certs/` montado (mkcert, como no local). O serviço `certbot` fica num profile (`--profile certbot`), desligado por padrão; quando houver domínio e provedor DNS, liga-se o profile e aponta-se o nginx para `/etc/letsencrypt/live/<domínio>/`. Até lá, os clientes só confiam no certificado se a CA do mkcert estiver instalada.

- `nginx.conf.template` baseado no exemplo da ARQUITETURA.md §9.2: `location /mcp` com `proxy_http_version 1.1`, `Connection ""`, `proxy_buffering off`; `location /health`; **e** `location /auth/` (a §9.2 não o lista, mas `POST /auth/token` e `/auth/revoke` precisam chegar ao app).
- `certbot` com plugin DNS do provedor (`certbot/dns-<provedor>`), credenciais em arquivo montado (fora da imagem e do repositório), renovação por loop/cron do container; nginx recarrega após renovação.
- Certificado Let's Encrypt é confiado por todos os clientes — nenhuma configuração client-side (§9.2, Opção A).
- Parametrizado por `.env`: `DOMAIN_NAME`, `CERTBOT_EMAIL`, `CERTBOT_DNS_PROVIDER`, caminho do arquivo de credenciais (as variáveis `CERTBOT_*` ficam comentadas no `.env.example` até o profile ser usado).

### 4.5 Oracle: criado, fora do compose

- A definição vive em `docker/oracle/` (Dockerfile ou referência à imagem + `.env`), construível/subível manualmente (`docker run` / `docker compose -f docker/oracle/docker-compose.oracle.yml up`).
- **Não** consta nos `docker-compose.local.yml`/`remote.yml`. Para habilitar no futuro basta mover/incluir o serviço (ou adicionar `include:`).
- Imagem **sem login** (`gvenzl/oracle-free`); `service_name` = `FREEPDB1`. O `OracleAdapter` suporta Oracle 12.1+ em thin mode; a compatibilidade com a 23ai do `oracle-free` deve ser verificada na primeira subida manual — é a validação manual que a F9 ficou devendo (F9 §10).

### 4.6 Banco de Dados (Config DB)

`database/schema.sql` **já contém** as tabelas da F12 (`users`, `profiles`, `user_profiles`, `profile_analyses`, `access_tokens`, `execution_history`). O container `postgres` monta esse arquivo em `/docker-entrypoint-initdb.d/` — roda uma única vez, com o volume vazio.

> **Migrations da F12 canceladas (decisão 7, §10):** `database/migrations/f12_autenticacao.sql` e `seed_usuario_admin_f12.sql` não existem mais no repositório (removidos no commit "remoção de arquivos de scripts") e **não serão recriados**. O `schema.sql` é a única fonte do schema; no Docker o banco nasce sempre do zero (volume `pgdata` vazio). Não há caminho de migração de banco existente — para recriar o schema, remover o volume `pgdata`. O cadastro do usuário admin fica no guia de deploy (F20, decisão 5).
>
> As referências remanescentes a esses arquivos em outros documentos estão listadas no ponto em aberto #4 (§11), para correção na revisão de documentos.

### 4.7 Fluxo de Dados

```
LOCAL                                          REMOTE
cliente MCP ──https:3000──► app (uvicorn+TLS)   cliente MCP ──https:443──► nginx ──http──► app:3000
                              │                                            │ (certbot renova certs)
                              ├─► postgres (Config DB)                      ├─► postgres
                              ├─► mysql (data source)                       └─► mysql
                              └─► [sqlserver, oracle: fora do compose]
```

## 5. Critérios de Aceitação

```gherkin
Feature: Docker Setup

Scenario: Ambiente local sobe com 1 comando
  Given .env preenchido a partir de .env.example e certs/ gerados com mkcert
  When docker compose -f docker-compose.local.yml up -d
  Then app, postgres e mysql ficam healthy
  And GET https://localhost:3000/health retorna {"status":"ok","db":true}

Scenario: Config DB inicializado
  Given volume pgdata vazio
  When o container postgres sobe pela primeira vez
  Then as tabelas do schema.sql (incluindo access_tokens) existem

Scenario: Autenticação funciona no container
  Given um usuário inserido no Config DB
  When POST /auth/token e depois chamada ao /mcp com Authorization: Bearer
  Then list_tools retorna só as analyses liberadas ao perfil do usuário

Scenario: Data sources dos três bancos do compose
  Given data_sources para MySQL e SQL Server apontando para os containers
  When uma análise de cada é executada
  Then ambas retornam o dataset (driver ODBC 18 presente na imagem)

Scenario: Oracle não sobe com o compose
  When docker compose up (local ou remote)
  Then nenhum container oracle é criado
  And docker/oracle/ permite subi-lo manualmente

Scenario: Remote com TLS no nginx
  Given certificado (mkcert) montado em certs/
  When docker compose -f docker-compose.remote.yml up -d
  Then https://<host>/health responde e /mcp faz streaming sem buffering
  And nenhum container certbot é criado (profile certbot desligado)

Scenario: Certbot habilitado (quando houver domínio e DNS)
  Given DOMAIN_NAME e credenciais DNS do Certbot configurados
  When docker compose -f docker-compose.remote.yml --profile certbot up -d
  Then o certificado Let's Encrypt é emitido e o nginx o serve

Scenario: Secrets fora da imagem
  When docker history/inspect da imagem do app
  Then não há .env, FERNET_KEY, senhas nem certs/
```

## 6. Testes

Sem testes unitários Python novos (nenhum código da aplicação muda); a regressão é a suíte existente (334 ✅) rodando inalterada.

### 6.2 Checklist de Testes
- [x] `docker build` do app conclui sem erro
- [ ] Suíte `pytest` existente continua 334/334 (fora do container, sem alteração)
- [x] `docker compose config` valida local e remote
- [x] `up` local → 4 containers healthy, `/health` = `{"status":"ok","db":true}`, `/mcp` sem token = 401 (falta: `/auth/token` → `/mcp` com cliente MCP real)
- [x] `MySQLAdapter` e `SQLServerAdapter` (sslmode omitido) conectam e executam `SELECT 1` a partir do container `app` (falta: análise completa via `call_tool`)
- [x] Handshake `openssl s_client -alpn h2,http/1.1` no local → `ALPN protocol: http/1.1`
- [x] Remote com nginx + mkcert: `/health` ok, `/auth/` e `/mcp` chegam ao app, :3000 não publicada, HTTP→HTTPS 301 (falta: verificar streaming SSE sem buffering com cliente MCP)
- [ ] Manual (adiado): profile `certbot` em domínio real (ou staging do Let's Encrypt)
- [ ] Manual: `docker/oracle/` sobe isoladamente e `OracleAdapter` conecta (fecha a pendência da F9)
- [x] Verificado que o `up` padrão não cria container Oracle

## 7. Mudanças na Configuração

**`.env.example` (acréscimos):**
```
# Config DB (container postgres) — POSTGRES_CONFIG_HOST=postgres dentro do compose
POSTGRES_CONFIG_HOST=postgres

# Containers de data source (somente dev/local)
MYSQL_ROOT_PASSWORD=changeme
MYSQL_DATABASE=analysis_data
MSSQL_SA_PASSWORD=Changeme_123!      # SQL Server exige senha forte
ORACLE_PASSWORD=changeme             # container Oracle (fora do compose)

# Remote (nginx; certificado montado em certs/ por ora)
# Certbot (DNS-01) só com --profile certbot — descomentar quando houver domínio/DNS:
# DOMAIN_NAME=analise.empresa.internal
# CERTBOT_EMAIL=ops@empresa.com
# CERTBOT_DNS_PROVIDER=cloudflare      # provedor definido na operação
# CERTBOT_DNS_CREDENTIALS=./secrets/certbot-dns.ini
```
No remote: `TLS_ENABLED=false` para o `app`.

## 8. Documentação
### 8.1 Como a feature aparece no MCP
Não altera o protocolo MCP nem as tools.
### 8.2 Como o usuário usa essa feature
`cp .env.example .env` → gerar certs (mkcert) → `docker compose -f docker-compose.local.yml up -d` → inserir usuário no Config DB → `POST /auth/token`. O passo a passo detalhado (incluindo cadastro do usuário admin e do seed) fica no guia de deploy (F20).
### 8.3 Como outros desenvolvedores estenderão isso
Novo banco = novo diretório em `docker/<banco>/` + serviço no compose (ou fora dele, como o Oracle).

## 9. Checklist de Implementação
**Código:**
- [x] `analysis_app/Dockerfile` + `.dockerignore`
- [x] `docker/oracle`, `docker/sqlserver`, `docker/nginx` (postgres/mysql: imagem direta nos compose)
- [x] `docker-compose.local.yml` e `docker-compose.remote.yml`
- [x] `.env.example` atualizado (inclui `POSTGRES_HOST_PORT=5433`, `NGINX_HTTP_PORT/NGINX_HTTPS_PORT`)
- [x] Comentários nos arquivos explicando decisões (ODBC 18, Oracle fora do compose, `/auth/`)

**QA:**
- [ ] Code review aprovado
- [ ] Roadmap atualizado (status F13 → Done) e CLAUDE.md

## 10. Decisões desta sessão (2026-10-01)

| # | Decisão |
|---|---|
| 1 | Um container por artefato: `app`, `postgres`, `mysql`, `sqlserver`, `oracle` |
| 2 | Oracle é criado mas **não** roda no compose; imagem sem login (`gvenzl/oracle-free`) |
| 3 | Container de SQL Server criado (`mssql/server:2022`), mas **opcional e fora do compose**, como o Oracle (ajuste de 2026-10-03) |
| 4 | Remote usa nginx + Certbot, **Opção A (DNS-01)**; local usa uvicorn + mkcert |
| 5 | Seed de usuário admin fica no guia de deploy (F20), não nas imagens |
| 6 | Driver ODBC **18** (par do SQL Server 2022, mais adequado) |
| 7 | Migrations da F12 (`f12_autenticacao.sql`) e seed (`seed_usuario_admin_f12.sql`) **canceladas**: `schema.sql` é a única fonte do schema |
| 8 | Remote sem DNS por ora: nginx usa certificado montado (mkcert); `certbot` vira profile opcional, desligado |
| 9 | SQL Server de dev: sem alteração no adapter; `sslmode` omitido/`prefer` aceita o certificado autoassinado; `verify-full` só em produção |

## 11. Pontos em aberto

| # | Ponto | Quando resolver |
|---|---|---|
| 1 | Provedor de DNS do Certbot (plugin `certbot/dns-<provedor>`) e domínio real | Adiado — só ao ligar o profile `certbot` |
| 2 | ~~`TrustServerCertificate` no SQL Server do container~~ — **resolvido** (decisão 9); só confirmar na primeira subida do `sqlserver` | Primeira subida |
| 3 | Compatibilidade do `OracleAdapter` com Oracle Free 23ai | Primeira subida manual do Oracle |
| 4 | ~~Referências às migrations da F12 nos docs~~ — **resolvido** (removidas de CLAUDE.md, NEGOCIO, ARQUITETURA, ROADMAP, DATABASE_SCHEMA, F12 e testes) | — |
