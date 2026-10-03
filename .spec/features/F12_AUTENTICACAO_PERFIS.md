# [F12] Autenticação e Controle de Acesso via Perfis

## Feature Spec

**ID:** F12
**Nome:** Autenticação e Controle de Acesso via Perfis
**Prioridade:** 🔴 Crítica
**Esforço Estimado:** 3.5d (28h) — era 2.5d; +1d pela emissão/revogação de token por e-mail e senha (endpoints, bcrypt, testes)
**Status:** 🟩 Done (2026-09-30)

---

## 1. Visão

Restringe `list_tools()`/`call_tool()` a usuários autenticados por token de acesso, e a quais analyses cada usuário pode ver/executar via um modelo de **perfis** (usuário N:N perfil N:N analyses). Substitui o modelo "rede interna confiável, sem autenticação" de V1.0 por um controle de acesso explícito, sem introduzir OAuth2/SSO. O próprio usuário emite (e revoga) os seus tokens por endpoints HTTP do servidor, informando **e-mail e senha** — sem depender de um administrador.

## 2. Objetivo

Garantir que cada chamada MCP seja de um usuário identificado, não bloqueado, e que só enxergue/execute analyses ativas vinculadas a um perfil ativo vinculado a ele — com bloqueio de usuário e mudança de permissão tendo efeito **imediato**, sem depender de expiração de token.

**Métrica de Sucesso:**
- ✅ Chamada MCP sem `Authorization` header, ou com token inválido/expirado/revogado, é recusada antes de qualquer consulta de negócio
- ✅ Usuário bloqueado (`is_blocked=true`) perde acesso imediatamente, mesmo com token não expirado, e não consegue emitir novo token
- ✅ `list_tools()` retorna somente analyses ativas vinculadas a um perfil ativo vinculado ao usuário autenticado
- ✅ `call_tool()` revalida a permissão — nunca confia apenas no que `list_tools()` já mostrou
- ✅ `execution_history` registra `user_id` de quem executou
- ✅ `POST /auth/token` emite um token opaco válido a partir de e-mail e senha válidos, e só nesse caso
- ✅ `POST /auth/revoke` revoga um token do próprio usuário, após validar e-mail e senha
- ✅ A senha nunca é persistida em texto puro (hash bcrypt)

## 3. Contexto

**Depende de:**
- F5 (MCP Tools Integration) — `list_tools()`/`call_tool()` já existentes em `mcp_transport/tools.py`, ponto de integração do auth ✅
- F8 (Log de Execução) — `AuditService.log_execution()`/`execution_history` já existentes, ganham `user_id` ✅

**É dependência de:**
- F13 (Docker Setup) — imagem de produção interna já deve sair com autenticação obrigatória
- F17 (Unit Tests) — cobertura de `AuthService`/`token_auth.py`/`password_hash.py`/rotas de auth
- F18 (Integration Tests) — cenário multi-cliente passa a incluir tokens distintos por cliente

**Decisões confirmadas (sessão de 2026-09-28/29 — ver ARQUITETURA.md ADR-007 para o racional completo):**
- Token **opaco** (`secrets.token_urlsafe(32)`, hash SHA-256 persistido) — não JWT, não OAuth2
- Emissão **self-service por endpoint HTTP** (`POST /auth/token`, FastAPI, sobre TLS) com **e-mail + senha** — sem script de emissão e sem admin no meio. Só e-mail e senha válidos geram token
- Senha guardada como **hash bcrypt** em `users.password_hash`; e-mail em `users.external_id`, **sempre normalizado** (minúsculas, sem espaços nas pontas)
- Usuário bloqueado, sem senha cadastrada, inexistente ou com senha errada **não gera token** — todos com a mesma resposta genérica
- **Sem proteção contra tentativas de senha** (rate limit/bloqueio) em V1.0 — só log (§4.5); ver §10, item 8
- **N tokens por usuário**, ilimitados, cada um com `label` opcional
- Expiração padrão **90 dias** (`ACCESS_TOKEN_EXPIRATION_DAYS`); o usuário pode pedir outra via `expire_days`, limitada por `ACCESS_TOKEN_MAX_EXPIRATION_DAYS`
- **Revogação** por `POST /auth/revoke` (e-mail + senha + token); sem endpoint de listagem
- Renovação **manual** — o usuário chama `POST /auth/token` de novo quando o token expira, sem tool MCP de auto-renovação
- Permissão (usuário → perfil → analyses) é **recalculada a cada chamada**, nunca cacheada no token
- `execution_history` ganha `user_id` (nullable) — quem executou cada análise
- **Sem CRUD de usuário**: usuários (com `password_hash` já gerado) são cadastrados por INSERT direto
- **Sem modo de desenvolvimento sem autenticação** (nada de `AUTH_ENABLED=false`): a autenticação é sempre obrigatória, e os testes a contornam por fixtures/patch do `AuthService` (§6.3) — sem flag que possa ir desligada para produção
- **A permissão de `list_tools()` é uma query em `AnalysisRepository`** (`get_allowed_for_user`), sem novo parâmetro no construtor do `AnalysisService` — os testes existentes do serviço não mudam de construtor (§6.3)

---

## 4. Descrição Técnica

### 4.1 Componentes Afetados

```
Componentes novos:
├─ routes/__init__.py                # pacote das rotas HTTP (fora do /mcp)
├─ routes/auth.py                    # APIRouter(prefix="/auth"): POST /auth/token, POST /auth/revoke
├─ security/token_auth.py            # generate_token(), hash_token()
├─ security/password_hash.py         # verify_password() — bcrypt; roda em thread (asyncio.to_thread)
├─ security/auth_middleware.py       # middleware ASGI em /mcp: 401 + contextvar do AuthenticatedUser (ver §4.2)
├─ services/auth_service.py          # AuthService.authenticate(), issue_token(), revoke_token(), is_analysis_allowed()
├─ repositories/user_repo.py         # UserRepository (get_by_id, get_by_external_id)
├─ repositories/profile_repo.py      # ProfileRepository (get_allowed_analysis_ids)
├─ repositories/access_token_repo.py # AccessTokenRepository
├─ schemas/auth.py                   # AuthenticatedUser, InvalidTokenError, InvalidCredentialsError, TokenRequest/Response, RevokeRequest
├─ tests/test_token_auth.py
├─ tests/test_password_hash.py
├─ tests/test_auth_service.py
├─ tests/test_auth_middleware.py
├─ tests/test_auth_routes.py         # POST /auth/token e POST /auth/revoke
├─ tests/test_mcp_tools_auth.py      # list_tools()/call_tool() com AuthenticatedUser
└─ tests/conftest.py                 # fixtures compartilhadas de auth e do `client` HTTP (ver §6.3)

Testes existentes ajustados (lista arquivo a arquivo em §6.3): test_mcp_tools.py, test_server_setup.py, test_execution_repo.py, test_audit_service.py, test_analysis_service.py, test_config.py

Componentes modificados:
├─ main.py                           # app.include_router(auth_router) — as rotas ficam em routes/, registradas aqui
├─ mcp_transport/__init__.py         # registra o middleware; handlers leem o contextvar (stateless=True já aplicado — obrigatório, ver §4.2 item 1); CORS expose_headers=["WWW-Authenticate"] (era "Mcp-Session-Id", nunca enviado em stateless)
├─ mcp_transport/tools.py            # list_tools()/call_tool() exigem AuthenticatedUser (ver §4.2, decisão técnica)
├─ repositories/analysis_repo.py     # get_allowed_for_user(user_id): analyses ativas de perfis ativos do usuário (JOIN — §4.2 passo 3)
├─ services/analysis_service.py      # get_allowed_analyses(user_id) delega ao repositório; execute(..., user_id=) repassado ao Audit
├─ services/audit_service.py         # log_execution(..., user_id=)
├─ repositories/execution_repo.py    # grava execution_history.user_id
├─ database/schema.sql               # + tabelas users (com password_hash), profiles, user_profiles, profile_analyses, access_tokens; + execution_history.user_id; + índices
├─ config.py                         # ACCESS_TOKEN_EXPIRATION_DAYS (default 90), ACCESS_TOKEN_MAX_EXPIRATION_DAYS (default 365)
├─ requirements.txt                  # + bcrypt
└─ .spec/{NEGOCIO,ARQUITETURA,DATABASE_SCHEMA,FEATURES_ROADMAP}.md — já atualizados nesta revisão

Sem mudança:
├─ adapters/*, VolumeGuardService, CacheService — nenhum dos dois conhece "usuário"
├─ /health e a rota /mcp em si (o middleware de auth só envolve o /mcp)
└─ Schema de data_sources/analyses/analysis_steps (analyses.parameters não muda)

Removidos do desenho anterior: scripts/generate_access_token.py e tests/test_generate_access_token.py (não há mais emissão por script)
```

As rotas HTTP ficam numa pasta própria (`routes/`), uma por assunto, e são registradas em `main.py` com `include_router`. `/health` continua em `main.py` (fora do escopo deste ajuste).

**Sem SQLAlchemy/Alembic:** o projeto acessa o Config DB direto com asyncpg (`PostgreSQLAdapter`) e o schema vive em `database/schema.sql`, aplicado à mão — não há `models.py` nem migrations Alembic. O F12 segue esse padrão: acrescenta as tabelas ao `schema.sql`. (A migration `f12_autenticacao.sql` prevista inicialmente foi cancelada — F13, decisão 7.) (A árvore de pastas de ARQUITETURA §5.2 citava `models.py`/Alembic como planejado; foi corrigida.)

**Instância única do `AuthService`:** o middleware, as rotas `/auth/*` e `mcp_transport/tools.py` precisam do mesmo `AuthService`. Ele é criado uma vez em `mcp_transport/tools.py` (onde já vivem os singletons `analysis_service`, `_audit_service` etc.), `routes/auth.py::get_auth_service()` devolve essa instância, e `configure_mcp()` entrega `auth_service.authenticate` ao middleware. É o ponto que os testes patcham (`tools.auth_service.is_analysis_allowed`, §6.3).

### 4.2 Fluxo de Dados

```
1. Cliente MCP envia Authorization: Bearer <token> em toda requisição ao /mcp
2. AuthService.authenticate(raw_token):
   ├─ hash = sha256(raw_token)
   ├─ AccessTokenRepository.get_by_hash(hash)
   │    └─ não encontrado, revoked_at != NULL, ou expires_at < now() → InvalidTokenError,
   │       PARA aqui (nenhuma query de negócio é feita)
   ├─ UserRepository.get_by_id(token.user_id)
   │    └─ não encontrado ou is_blocked=true → InvalidTokenError, PARA aqui
   ├─ AccessTokenRepository.touch_last_used(token.id) — observabilidade, não bloqueia
   │  o fluxo mesmo se falhar
   └─ Retorna AuthenticatedUser(id, name)

3. list_tools(current_user):
   └─ AnalysisService.get_allowed_analyses(current_user.id)
        └─ AnalysisRepository.get_allowed_for_user(current_user.id)
           SELECT DISTINCT a.* FROM analyses a
           JOIN profile_analyses pa ON pa.analysis_id = a.id
           JOIN user_profiles up    ON up.profile_id  = pa.profile_id
           JOIN profiles p          ON p.id = pa.profile_id
           WHERE up.user_id = :user_id AND a.is_active = true AND p.is_active = true

4. call_tool(name, arguments, current_user):
   ├─ Resolve a análise pelo nome (igual hoje — analysis_repo.get_by_name())
   ├─ análise inexistente/inativa → {"status": "error", ...} (comportamento já existente)
   ├─ REVALIDA a permissão: AuthService.is_analysis_allowed(current_user.id, analysis.id)
   │    └─ False → {"status": "error", "mensagem": "Acesso não autorizado a esta análise."}
   │       (mesmo se a tool apareceu num list_tools() anterior — perfil pode ter
   │       mudado, ou o usuário foi bloqueado, entre as duas chamadas)
   └─ AnalysisService.execute(analysis.id, arguments, ..., user_id=current_user.id)
        └─ AuditService.log_execution(..., user_id=current_user.id)
```

**Resposta de recusa de autenticação no `/mcp` (middleware, antes do SDK) — genérica, idêntica em todos os casos:**
```
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer
Content-Type: application/json

{"error": "unauthorized", "message": "Token de acesso inválido ou ausente."}
```
Aplica-se a: header `Authorization` ausente/malformado (não `Bearer <token>` — o esquema `Bearer` é aceito sem diferenciar maiúsculas/minúsculas, como no RFC 7235; token vazio é malformado), token inexistente, expirado, revogado, e usuário bloqueado ou inexistente. **O cliente nunca vê o motivo** — status, headers e corpo são os mesmos nos 5 casos. `InvalidTokenError` carrega sempre a mesma mensagem genérica. Falta de permissão numa análise (`call_tool()`) é outro caso: o usuário está autenticado, então não é 401 — segue o payload MCP `{"status": "error", ...}` do passo 4.

**Emissão de token — `POST /auth/token` (fora do `/mcp`, sem `Authorization` header):**
```
Requisição:
  POST /auth/token   (TLS obrigatório, como o resto do servidor)
  {
    "email": "maria@empresa.com",          # obrigatório
    "password": "...",                     # obrigatório
    "label": "Claude Desktop - notebook",  # opcional (texto livre → access_tokens.label)
    "expire_days": 30                      # opcional, inteiro >= 1; se ausente usa ACCESS_TOKEN_EXPIRATION_DAYS
  }

AuthService.issue_token(email, password, label, expire_days):
  ├─ email = email.strip().lower()                       # sempre normalizado
  ├─ UserRepository.get_by_external_id(email)
  ├─ verify_password(password, user.password_hash)       # bcrypt, em thread
  │    └─ usuário inexistente, password_hash NULL, senha errada, ou is_blocked=true
  │       → InvalidCredentialsError, PARA aqui — nenhum token é criado
  ├─ expire_days ausente → ACCESS_TOKEN_EXPIRATION_DAYS
  │  expire_days > ACCESS_TOKEN_MAX_EXPIRATION_DAYS → 400 (só depois das credenciais válidas)
  ├─ token = generate_token()                            # secrets.token_urlsafe(32)
  ├─ AccessTokenRepository.create(user.id, hash_token(token), now()+expire_days, label)
  └─ Devolve o token bruto 1 única vez — nunca fica salvo em texto puro

Resposta 200:
  {"token": "<opaco>", "token_type": "Bearer", "expires_at": "2026-12-28T12:00:00Z"}

Resposta 401 (credenciais inválidas — idêntica nos 4 casos acima):
  {"error": "invalid_credentials", "message": "E-mail ou senha inválidos."}

Resposta 400 (expire_days acima do máximo):
  {"error": "invalid_expire_days", "message": "expire_days máximo: <ACCESS_TOKEN_MAX_EXPIRATION_DAYS>."}
```
Corpo mal formado, `expire_days < 1` ou campo acima do tamanho máximo (`email`/`label` 255, `password`/`token` 256): validação padrão do FastAPI/Pydantic (422).

**Revogação de token — `POST /auth/revoke` (fora do `/mcp`, sem `Authorization` header):**
```
Requisição:
  POST /auth/revoke
  {"email": "...", "password": "...", "token": "<token a revogar>"}

AuthService.revoke_token(email, password, raw_token):
  ├─ valida e-mail e senha exatamente como em issue_token — PRIMEIRO
  │    └─ inválidas → InvalidCredentialsError (401 igual ao de /auth/token), PARA aqui
  ├─ AccessTokenRepository.get_by_hash(hash_token(raw_token))
  │    └─ não encontrado, OU token.user_id != user.id → TokenNotFoundError (404), PARA aqui
  └─ AccessTokenRepository.revoke(token.id)   # revoked_at = now(); token já revogado ou expirado também é aceito (200, sem erro)

Resposta 200:  {"status": "revoked"}
Resposta 401:  {"error": "invalid_credentials", "message": "E-mail ou senha inválidos."}
Resposta 404:  {"error": "token_not_found", "message": "Token não encontrado."}
```
A ordem importa: credenciais primeiro, token depois — sem e-mail e senha válidos, `/auth/revoke` nunca confirma nem nega a existência de um token. Um usuário só revoga os próprios tokens (o de outro usuário responde 404, como se não existisse).

**Decisão técnica (2026-09-29): transporte stateless + middleware ASGI com `contextvar`.**
O SDK `mcp` (`mcp>=1.9.0,<2.0.0`, classe de baixo nível `Server`, ver ADR-006) registra `list_tools()`/`call_tool()` sem um parâmetro de `Request` HTTP. Decidido:
1. **Pré-requisito já aplicado — obrigatório:** `StreamableHTTPSessionManager(app=mcp_server, stateless=True)` em `mcp_transport/__init__.py` (cada requisição HTTP é independente, sem `Mcp-Session-Id`). O motivo determinante é o `contextvar` (item 2): em stateless a task do servidor MCP nasce dentro de cada requisição e herda o usuário gravado pelo middleware; **em stateful ela nasce só no `initialize` e o `contextvar` fica congelado no usuário que abriu a sessão** — uma requisição posterior com o token de outro usuário seria validada pelo middleware, mas executada com as permissões do primeiro (comprovado em teste, 2026-09-30 — ARQUITETURA.md §14.1 item 8). O bloqueio imediato, sozinho, não exigiria stateless, porque o middleware valida toda requisição nos dois modos. Validado: F6 com 2+ clientes reais e `TestStatelessTransport` (`tests/test_server_setup.py`), 189/189 testes ✅.
2. **Middleware ASGI** em volta de `/mcp` (rota exata + mount `/mcp/...`) — **somente** o `/mcp`; `/health` e `/auth/*` ficam fora dele. Lê `Authorization: Bearer`, chama `AuthService.authenticate()`, responde **401 HTTP** em caso de `InvalidTokenError` (sem entrar no SDK), e guarda o `AuthenticatedUser` num `contextvar` do projeto. O middleware fica **dentro** do `CORSMiddleware` (que já é o mais externo, `configure_mcp`): o preflight `OPTIONS` (sem `Authorization`) é respondido pelo CORS antes de chegar à autenticação, e o 401 sai com os headers CORS — necessário para clientes desktop (Electron) que validam o conector por `fetch()`. O middleware grava o `contextvar` com `token = current_user.set(user)` e o restaura com `current_user.reset(token)` num `finally`, mesmo em caso de exceção. `WWW-Authenticate` entra em `expose_headers` do CORS — não é um header "safelisted", e um cliente Electron que leia o 401 via `fetch()` só o enxerga se exposto.
3. `list_tools()`/`call_tool()` em `mcp_transport/__init__.py` leem o `contextvar` e repassam o usuário a `tools.list_tools(current_user)`/`tools.call_tool(name, arguments, current_user)`.
4. Dois testes devem provar que o `contextvar` chega ao handler certo: (a) duas requisições **simultâneas** com tokens de usuários distintos não se misturam; (b) requisições **sequenciais** do mesmo cliente com tokens de usuários distintos (ex.: `initialize` como A, depois `tools/list` como B) chegam ao handler como B. O teste (b) é a proteção de regressão contra alguém trocar para `stateless=False`: nesse modo ele falha, porque o handler veria A.
Alternativas descartadas: (1) ler `mcp_server.request_context.request.headers` dentro dos handlers — funciona em stateless e stateful, mas depende de detalhe interno do SDK e não permite recusar em nível HTTP; (2) transporte stateful com a identidade guardada na sessão MCP — `contextvar` congelado no `initialize` (item 1), estado em memória por cliente, sessões perdidas em restart e sticky session em múltiplas réplicas. Ver ARQUITETURA.md §3.5, ADR-006 (v1.19/v1.21) e §14.1 item 8.

### 4.3 Banco de Dados

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    external_id VARCHAR(255) UNIQUE,   -- e-mail de login, cadastrado em minúsculas
    password_hash VARCHAR(255),        -- hash bcrypt ($2b$...); NULL = usuário não consegue emitir token
    is_blocked BOOLEAN NOT NULL DEFAULT false,   -- NOT NULL: um NULL não pode contar como "não bloqueado"
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE user_profiles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, profile_id)
);

CREATE TABLE profile_analyses (
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    analysis_id UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    PRIMARY KEY (profile_id, analysis_id)
);

CREATE TABLE access_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    label VARCHAR(255),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);

ALTER TABLE execution_history ADD COLUMN user_id UUID REFERENCES users(id);

-- (sem índice em token_hash: o UNIQUE de access_tokens.token_hash já cria um índice)
CREATE INDEX idx_access_tokens_user ON access_tokens(user_id);
CREATE INDEX idx_execution_history_user ON execution_history(user_id);
```

**Decisões de schema (confirmadas):**
- `users.external_id` passa a ser a **credencial de login (e-mail)**; `users.created_by` fica (opcional, sem uso pelo código do F12 — rastreia quem cadastrou o usuário).
- **`users.password_hash` (novo):** hash bcrypt gerado fora do código (ver §8.2). Nunca a senha. `NULL` = o usuário existe mas não consegue emitir token (as outras tabelas e a autorização não dependem dele).
- **O e-mail é cadastrado sempre em minúsculas**, à mão. A aplicação normaliza (`strip().lower()`) o e-mail recebido antes de buscar — não há `CHECK` no banco; um `external_id` gravado com maiúscula nunca casará com o login (erro de cadastro do admin, ver §10, item 9).
- `execution_history.user_id` **sem `ON DELETE`** (`NO ACTION`): não é possível apagar um usuário que já tenha execuções registradas — preserva a auditoria. Para retirar o acesso, usar `is_blocked = true`. Vínculos (`user_profiles`, `access_tokens`) usam `ON DELETE CASCADE`.
- Sem `idx_access_tokens_hash`: o `UNIQUE` em `token_hash` já cria o índice usado por `get_by_hash()`.
- **Datas de `access_tokens` são `TIMESTAMPTZ`** (o resto do schema usa `TIMESTAMP`): o asyncpg devolve `TIMESTAMP` como `datetime` **sem fuso**, e `expires_at < datetime.now(timezone.utc)` levantaria `TypeError` (naive × aware); com `TIMESTAMPTZ` volta um `datetime` com fuso e a comparação em Python funciona. `expires_at` sai na resposta de `/auth/token` em UTC (`...Z`).
- **`users.is_blocked` e `profiles.is_active` são `NOT NULL DEFAULT`:** sem isso, um INSERT manual com `is_blocked = NULL` contaria como "não bloqueado" (falha aberta). As tabelas antigas (`analyses`, `data_sources`) não mudam.
- **Aplicação do schema:** `database/schema.sql` (única fonte; migration cancelada — F13) — ver §4.1.

Ver DATABASE_SCHEMA.md §2.6-§2.10 para a descrição campo a campo, e ARQUITETURA.md §2.2 para o schema completo em ordem de criação.

**Cadastro de usuários/perfis/vínculos:** segue o mesmo padrão já usado para `analyses`/`data_sources` (UC1 em NEGOCIO.md) — `INSERT` direto nas tabelas, sem CRUD/endpoint dedicado, agora incluindo `external_id` (e-mail em minúsculas) e `password_hash`. Nenhuma interface administrativa é criada nesta feature (ver §10, Observações).

### 4.4 Endpoints/Interfaces

```python
# security/token_auth.py
def generate_token() -> str:
    """secrets.token_urlsafe(32)."""

def hash_token(raw_token: str) -> str:
    """SHA-256 hex do token bruto."""


# security/password_hash.py
def verify_password(password: str, password_hash: str | None) -> bool:
    """bcrypt.checkpw. Devolve False (nunca lança) se password_hash for None/inválido
    ou se a senha passar de 72 bytes (limite do bcrypt). Chamado via asyncio.to_thread()
    — bcrypt é CPU-bound e bloquearia o event loop.
    Para e-mail inexistente / password_hash NULL o AuthService confere a senha contra
    um hash bcrypt fictício (constante), para o tempo de resposta não revelar se o
    e-mail existe."""


# schemas/auth.py
@dataclass
class AuthenticatedUser:
    id: UUID
    name: str

class AuthFailureReason(str, Enum):
    MISSING_HEADER = "missing_header"
    MALFORMED_HEADER = "malformed_header"
    TOKEN_NOT_FOUND = "token_not_found"
    TOKEN_EXPIRED = "token_expired"
    TOKEN_REVOKED = "token_revoked"
    USER_BLOCKED = "user_blocked"
    USER_NOT_FOUND = "user_not_found"

class InvalidTokenError(Exception):
    """Token ausente, inválido, expirado, revogado, ou usuário bloqueado/inexistente.
    A mensagem é sempre a mesma genérica ("Token de acesso inválido ou ausente.") —
    o motivo nunca é exposto ao cliente (ver §4.2). O motivo real vai em atributos
    internos, usados só para o log do servidor (ver §4.5):
        reason: AuthFailureReason
        token_id: UUID | None   # quando o token foi encontrado
        user_id: UUID | None    # quando o token foi encontrado"""

class LoginFailureReason(str, Enum):
    USER_NOT_FOUND = "user_not_found"
    NO_PASSWORD = "no_password"
    WRONG_PASSWORD = "wrong_password"
    USER_BLOCKED = "user_blocked"

class InvalidCredentialsError(Exception):
    """E-mail/senha inválidos (inexistente, sem senha, senha errada ou usuário bloqueado).
    Mensagem sempre genérica ("E-mail ou senha inválidos."); o motivo real vai em
    `reason: LoginFailureReason` e `user_id: UUID | None`, só para o log (§4.5)."""

class TokenNotFoundError(Exception):
    """Token inexistente ou de outro usuário, em /auth/revoke (após credenciais válidas)."""

class ExpireDaysTooLargeError(Exception):
    """expire_days > ACCESS_TOKEN_MAX_EXPIRATION_DAYS (mapeado para 400)."""

class TokenRequest(BaseModel):
    email: str = Field(max_length=255)             # = tamanho de users.external_id
    password: str = Field(max_length=256)          # limita o corpo; o bcrypt só aceita 72 bytes de qualquer forma
    label: str | None = Field(default=None, max_length=255)   # = tamanho de access_tokens.label; sem isso o Postgres devolveria 500
    expire_days: int | None = Field(default=None, ge=1)

class TokenResponse(BaseModel):
    token: str
    token_type: str = "Bearer"
    expires_at: datetime

class RevokeRequest(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=256)
    token: str = Field(max_length=256)             # token_urlsafe(32) tem 43 caracteres


# repositories/access_token_repo.py
class AccessTokenRepository:
    async def get_by_hash(self, token_hash: str) -> AccessToken | None: ...
    async def create(self, user_id: UUID, token_hash: str, expires_at: datetime, label: str | None) -> AccessToken: ...
    async def touch_last_used(self, token_id: UUID) -> None: ...
    async def revoke(self, token_id: UUID) -> None: ...


# repositories/user_repo.py
class UserRepository:
    async def get_by_id(self, user_id: UUID) -> User | None: ...
    async def get_by_external_id(self, external_id: str) -> User | None:
        """Recebe o e-mail já normalizado (minúsculas)."""


# repositories/profile_repo.py
class ProfileRepository:
    async def get_allowed_analysis_ids(self, user_id: UUID) -> set[UUID]:
        """Mesma regra do list_tools(): JOIN profile_analyses + user_profiles + profiles
        + analyses, com profiles.is_active = true E analyses.is_active = true.
        Usado só por AuthService.is_analysis_allowed() (revalidação no call_tool()).
        A query de list_tools() é AnalysisRepository.get_allowed_for_user() — mesma regra,
        devolvendo as linhas de analyses; um teste de integração garante que as duas
        concordam (§6.2)."""


# repositories/analysis_repo.py (modificado)
class AnalysisRepository:
    async def get_allowed_for_user(self, user_id: UUID) -> list[Analysis]:
        """SELECT DISTINCT a.* ... (§4.2 passo 3) — analyses ativas vinculadas a um
        perfil ativo vinculado ao usuário. Sem novo parâmetro no construtor do
        AnalysisService: ele já recebe o AnalysisRepository."""


# services/auth_service.py
class AuthService:
    def __init__(self, token_repo: AccessTokenRepository, user_repo: UserRepository, profile_repo: ProfileRepository):
        ...

    async def authenticate(self, raw_token: str) -> AuthenticatedUser:
        """Levanta InvalidTokenError se token ausente/inválido/expirado/revogado
        ou usuário inexistente/bloqueado. Nunca lança para "análise não permitida"
        — isso é is_analysis_allowed(), chamado depois, já com o usuário resolvido."""

    async def issue_token(self, email: str, password: str, label: str | None, expire_days: int | None) -> tuple[str, datetime]:
        """Valida e-mail/senha (InvalidCredentialsError), aplica ACCESS_TOKEN_EXPIRATION_DAYS
        se expire_days for None, recusa acima de ACCESS_TOKEN_MAX_EXPIRATION_DAYS
        (ExpireDaysTooLargeError) e devolve (token_bruto, expires_at)."""

    async def revoke_token(self, email: str, password: str, raw_token: str) -> None:
        """Valida e-mail/senha PRIMEIRO (InvalidCredentialsError); depois localiza o token
        (TokenNotFoundError se inexistente ou de outro usuário) e o revoga."""

    async def is_analysis_allowed(self, user_id: UUID, analysis_id: UUID) -> bool:
        """analysis_id in get_allowed_analysis_ids(user_id) — reconsulta o BD a cada
        chamada, sem cache. Usado por call_tool() na revalidação; list_tools() usa
        AnalysisService.get_allowed_analyses() (mesma regra)."""


# routes/auth.py  (registrado em main.py com app.include_router)
router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/token", response_model=TokenResponse)
async def issue_token(body: TokenRequest, request: Request) -> TokenResponse: ...

@router.post("/revoke")
async def revoke_token(body: RevokeRequest, request: Request) -> dict: ...


# services/analysis_service.py (modificado)
async def get_allowed_analyses(self, user_id: UUID) -> list[Analysis]:
    """Delega a AnalysisRepository.get_allowed_for_user(user_id). get_all_analyses()
    continua existindo, sem filtro por usuário (uso interno; list_tools() deixa de usá-lo)."""

async def execute(self, analysis_id: UUID, params: dict, confirmar_volume_alto: bool = False, user_id: UUID | None = None) -> dict:
    """Assinatura existente + user_id opcional, repassado a AuditService.log_execution()."""


# services/audit_service.py e repositories/execution_repo.py (modificados)
async def log_execution(self, analysis_id, parameters, status, execution_time_ms, cached,
                        result=None, error_message=None, user_id: UUID | None = None) -> None:
    """user_id opcional (default None) e por último: as chamadas e os testes existentes
    continuam válidos. Repassado a ExecutionRepository.create(..., user_id=)."""

# ExecutionRepository.create(..., cached, user_id: UUID | None = None): INSERT com 10 colunas,
# user_id como $10 (as posições $1-$9 não mudam).


# routes/auth.py — o AuthService chega às rotas por dependência do FastAPI, para os testes
# poderem trocá-lo com app.dependency_overrides sem subir o app real (ver §6.3)
def get_auth_service() -> AuthService: ...


# mcp_transport/tools.py (modificado)
async def list_tools(current_user: AuthenticatedUser) -> list[Tool]: ...

async def call_tool(name: str, arguments: dict, current_user: AuthenticatedUser) -> dict: ...
```

**Tipo dos identificadores (decisão): `UUID` (`uuid.UUID`) em todo o código Python do F12** — `AuthenticatedUser.id`, `InvalidTokenError.token_id/user_id`, `user_id`/`analysis_id` em `AuthService`, repositórios, `AnalysisService.execute(..., user_id=)`, `AuditService.log_execution()` e `ExecutionRepository.create()`. Sem conversão para `str` fora das bordas:
- **Leitura do BD:** o `PostgreSQLAdapter` (asyncpg) já devolve colunas `UUID` como `uuid.UUID` — é o que `Analysis.id`/`DataSource.id` já fazem hoje, então `User.id`, `AccessToken.id`/`user_id` seguem o mesmo padrão sem código extra.
- **Escrita no BD:** `UUID` é passado direto como parâmetro `$n` (igual `analysis_id` em `ExecutionRepository.create()`).
- **Borda de log:** `%s`/f-string de `UUID` já produz o formato canônico com hífens (§4.5).
- **Borda JSON:** o `AuthenticatedUser` nunca é serializado para o cliente MCP; `execution_history.parameters` continua usando `default=str`. Os endpoints `/auth/*` não devolvem ids.

### 4.5 Log de Falhas de Autenticação e Autorização

Como o cliente não vê o motivo da recusa (§4.2), o servidor registra o motivo real em log — é o único meio de o admin descobrir por que um token ou um login falhou. Usa o `logging` padrão já configurado em `main.py` (stdout), sem tabela nova: `execution_history` (F8) continua registrando só execuções, não tentativas recusadas.

| Evento | Onde é logado | Nível | Campos |
|---|---|---|---|
| Recusa de autenticação no `/mcp` (qualquer `AuthFailureReason`) | `security/auth_middleware.py`, ao capturar `InvalidTokenError` | `WARNING` | `reason`, `client_ip`, `method`, `path`, `token_id` e `user_id` (só quando o token foi encontrado) |
| Acesso negado a uma análise (`is_analysis_allowed() == False`) | `mcp_transport/tools.py` — `call_tool()` | `WARNING` | `user_id`, `analysis_id`, `analysis_name` |
| Token válido, `touch_last_used` falhou | `AuthService.authenticate()` | `WARNING` | `token_id`, erro — não bloqueia a chamada (§4.2) |
| Credenciais inválidas em `/auth/token` ou `/auth/revoke` (qualquer `LoginFailureReason`) | `routes/auth.py`, ao capturar `InvalidCredentialsError` | `WARNING` | `endpoint`, `reason`, `client_ip`, `user_id` (só quando o e-mail existe) |
| Token não encontrado em `/auth/revoke` (credenciais válidas) | `routes/auth.py` | `WARNING` | `endpoint`, `client_ip`, `user_id` |
| Token emitido / revogado | `routes/auth.py` | `INFO` | `user_id`, `token_id`, `label`, `expires_at` (emissão) |

Formato (chave=valor, uma linha):
```
WARNING security.auth_middleware: auth_failed reason=token_expired client_ip=10.0.0.15 method=POST path=/mcp token_id=<uuid> user_id=<uuid>
WARNING mcp_transport.tools: access_denied user_id=<uuid> analysis_id=<uuid> analysis_name=custos_financeiros
WARNING routes.auth: login_failed endpoint=/auth/token reason=wrong_password client_ip=10.0.0.15 user_id=<uuid>
INFO routes.auth: token_issued user_id=<uuid> token_id=<uuid> label="Claude Desktop" expires_at=2026-12-28T12:00:00Z
```

**Regras de segurança do log:**
- **Nunca** logar o token bruto, o header `Authorization`, o `token_hash`, **a senha nem o `password_hash`** — nem parcialmente. **O e-mail informado também não é logado** (o campo pode ter sido digitado errado, inclusive com a senha): quando o e-mail existe, o log traz o `user_id`; quando não existe, só o IP.
- `client_ip` vem de `scope["client"]`/`request.client`. Atrás de proxy reverso (nginx, ARQUITETURA.md §9) isso seria o IP do proxy, e o IP real exigiria `X-Forwarded-For` de um proxy confiável — fora do escopo do F12 (ver §10, item 7).
- O motivo (`reason`) fica só no log; o corpo do 401 continua idêntico em todos os casos de cada endpoint.
- Sem log de sucesso de autenticação no `/mcp`: o volume seria 1 linha por chamada, e o rastro de quem executou o quê já está em `execution_history.user_id`; `access_tokens.last_used_at` cobre "quando o token foi usado pela última vez". Emissão e revogação de token, por serem raras, são logadas em `INFO`.

---

## 5. Critérios de Aceitação

```gherkin
Feature: Autenticação por token e controle de acesso via perfis

Scenario: Requisição sem token é recusada
  Given Nenhum header Authorization é enviado
  When O cliente MCP chama list_tools() ou call_tool()
  Then O servidor recusa antes de qualquer consulta a analyses/perfis

Scenario: Token expirado é recusado
  Given Um access_tokens.expires_at no passado
  When O cliente chama list_tools() com esse token
  Then O servidor recusa, mesmo que o token nunca tenha sido revogado

Scenario: Token revogado é recusado
  Given Um access_tokens.revoked_at preenchido
  When O cliente chama call_tool() com esse token
  Then O servidor recusa

Scenario: Usuário bloqueado perde acesso imediatamente
  Given Um usuário com is_blocked=true e um token ainda válido (não expirado)
  When O cliente chama list_tools() ou call_tool()
  Then O servidor recusa, sem consultar analyses/perfis

Scenario: list_tools() retorna só as analyses permitidas
  Given Usuário vinculado ao perfil "Comercial", vinculado à análise "vendas_por_regiao" (ativa)
  And A análise "custos_financeiros" (ativa) não está vinculada a nenhum perfil do usuário
  When O usuário chama list_tools()
  Then A lista inclui "execute_vendas_por_regiao"
  And A lista NÃO inclui "execute_custos_financeiros"

Scenario: call_tool() revalida mesmo após list_tools() ter mostrado a tool
  Given Usuário via list_tools() viu "execute_vendas_por_regiao" (perfil "Comercial" vinculado)
  And Entre as duas chamadas, o vínculo perfil↔análise foi removido (ou o perfil foi desativado)
  When O usuário chama call_tool("execute_vendas_por_regiao", params)
  Then O servidor recusa por falta de permissão, mesmo a tool tendo aparecido antes

Scenario: Perfil inativo não libera acesso
  Given Usuário vinculado a um perfil com is_active=false, vinculado à análise "x"
  When O usuário chama call_tool("execute_x", params)
  Then O servidor recusa — perfil inativo não conta, mesmo com o vínculo existindo

Scenario: Usuário sem nenhum perfil vinculado
  Given Usuário sem nenhuma linha em user_profiles
  When O usuário chama list_tools()
  Then A lista retornada é vazia

Scenario: Execução bem-sucedida registra o usuário
  Given Usuário autorizado executa "execute_vendas_por_regiao" com sucesso
  When A execução é registrada
  Then execution_history.user_id corresponde ao usuário autenticado

Scenario: Emissão de token com e-mail e senha válidos
  Given Um usuário em `users` com external_id "maria@empresa.com" e password_hash bcrypt de "s3nha", não bloqueado
  When O cliente chama POST /auth/token com {"email": "maria@empresa.com", "password": "s3nha"}
  Then Responde 200 com token, token_type "Bearer" e expires_at = now() + ACCESS_TOKEN_EXPIRATION_DAYS
  And access_tokens.token_hash correspondente é criado
  And O valor bruto do token não é persistido em nenhuma tabela

Scenario: E-mail é normalizado na emissão
  Given O mesmo usuário
  When O cliente chama POST /auth/token com {"email": "  Maria@Empresa.COM ", "password": "s3nha"}
  Then Responde 200 — o e-mail é normalizado (strip + minúsculas) antes da busca

Scenario: Emissão com label e expire_days
  Given Credenciais válidas
  When O cliente chama POST /auth/token com "label": "Claude Desktop" e "expire_days": 30
  Then access_tokens.label = "Claude Desktop" e expires_at = now() + 30 dias

Scenario: expire_days acima do máximo
  Given Credenciais válidas e ACCESS_TOKEN_MAX_EXPIRATION_DAYS=365
  When O cliente chama POST /auth/token com "expire_days": 400
  Then Responde 400 e nenhum token é criado

Scenario: expire_days inválido
  Given Credenciais válidas
  When O cliente chama POST /auth/token com "expire_days": 0
  Then Responde 422 (validação) e nenhum token é criado

Scenario: Credenciais inválidas não geram token e não revelam o motivo
  Given Quatro casos: e-mail inexistente, usuário sem password_hash, senha errada, usuário bloqueado
  When O cliente chama POST /auth/token em cada um
  Then Todos recebem 401 com o mesmo corpo {"error": "invalid_credentials", "message": "E-mail ou senha inválidos."}
  And Nenhuma linha é criada em access_tokens

Scenario: Revogação com credenciais válidas
  Given Usuário X com um token ativo
  When O cliente chama POST /auth/revoke com o e-mail e a senha de X e esse token
  Then Responde 200 {"status": "revoked"}
  And access_tokens.revoked_at é preenchido
  And Chamadas ao /mcp com esse token passam a receber 401

Scenario: Revogação valida as credenciais antes de olhar o token
  Given Credenciais inválidas e um token que existe
  When O cliente chama POST /auth/revoke
  Then Responde 401 (o mesmo de /auth/token) — sem confirmar nem negar a existência do token

Scenario: Revogação de token inexistente ou de outro usuário
  Given Credenciais válidas do usuário X e um token que não existe (ou pertence ao usuário Y)
  When O cliente chama POST /auth/revoke
  Then Responde 404 {"error": "token_not_found", "message": "Token não encontrado."}
  And O token do usuário Y permanece ativo

Scenario: Recusa de autenticação no /mcp não revela o motivo
  Given Cinco requisições recusadas: sem header, token inexistente, token expirado, token revogado, usuário bloqueado
  When O servidor responde a cada uma
  Then Todas recebem 401, header "WWW-Authenticate: Bearer" e o mesmo corpo
       {"error": "unauthorized", "message": "Token de acesso inválido ou ausente."}

Scenario: Falha de autenticação é registrada em log com o motivo real
  Given Um token expirado
  When O cliente chama o /mcp com esse token
  Then O cliente recebe o 401 genérico
  And O log do servidor contém um WARNING "auth_failed" com reason=token_expired, o client_ip, o token_id e o user_id
  And Nenhuma linha do log contém o token bruto, o header Authorization ou o token_hash

Scenario: Falha de login é registrada em log sem senha nem e-mail
  Given Um usuário existente e uma senha errada
  When O cliente chama POST /auth/token
  Then O log contém um WARNING "login_failed" com reason=wrong_password, client_ip e user_id
  And Nenhuma linha do log contém a senha, o password_hash ou o e-mail informado

Scenario: Acesso negado a uma análise é registrado em log
  Given Usuário autenticado sem permissão na análise "custos_financeiros"
  When O usuário chama call_tool("execute_custos_financeiros", params)
  Then O log do servidor contém um WARNING "access_denied" com user_id, analysis_id e analysis_name

Scenario: Múltiplos tokens do mesmo usuário são independentes
  Given Usuário X com dois tokens (label "Claude Desktop" e "Gemini Desktop")
  When O token "Claude Desktop" é revogado via POST /auth/revoke
  Then Chamadas com o token "Gemini Desktop" continuam autenticando normalmente
```

---

## 6. Testes

### 6.1 Testes Unitários

```python
# tests/test_token_auth.py
class TestTokenAuth:
    def test_generate_token_is_url_safe_and_unique(self): ...
    def test_hash_token_is_deterministic_sha256(self): ...


# tests/test_password_hash.py
class TestPasswordHash:
    def test_verify_password_correct(self): ...
    def test_verify_password_wrong(self): ...
    def test_verify_password_none_hash_returns_false(self): ...
    def test_verify_password_over_72_bytes_returns_false(self): ...


# tests/test_auth_service.py
class TestAuthService:
    @pytest.mark.asyncio
    async def test_authenticate_success(self): ...
    @pytest.mark.asyncio
    async def test_authenticate_token_not_found(self): ...
    @pytest.mark.asyncio
    async def test_authenticate_token_expired(self): ...
    @pytest.mark.asyncio
    async def test_authenticate_token_revoked(self): ...
    @pytest.mark.asyncio
    async def test_authenticate_user_blocked(self): ...
    @pytest.mark.asyncio
    async def test_authenticate_user_not_found(self): ...
    @pytest.mark.asyncio
    async def test_is_analysis_allowed_true(self): ...
    @pytest.mark.asyncio
    async def test_is_analysis_allowed_false_no_profile(self): ...
    @pytest.mark.asyncio
    async def test_is_analysis_allowed_false_profile_inactive(self): ...
    @pytest.mark.asyncio
    async def test_is_analysis_allowed_false_analysis_inactive(self): ...
    @pytest.mark.asyncio
    async def test_issue_token_success_default_expiration(self): ...
    @pytest.mark.asyncio
    async def test_issue_token_custom_expire_days_and_label(self): ...
    @pytest.mark.asyncio
    async def test_issue_token_normalizes_email(self): ...
    @pytest.mark.asyncio
    async def test_issue_token_expire_days_above_max_raises(self): ...
    @pytest.mark.asyncio
    async def test_issue_token_invalid_credentials_per_reason(self): ...  # inexistente, sem senha, senha errada, bloqueado → InvalidCredentialsError com o reason certo
    @pytest.mark.asyncio
    async def test_issue_token_never_persists_raw_token(self): ...
    @pytest.mark.asyncio
    async def test_revoke_token_success(self): ...
    @pytest.mark.asyncio
    async def test_revoke_token_validates_credentials_before_token_lookup(self): ...
    @pytest.mark.asyncio
    async def test_revoke_token_of_other_user_raises_not_found(self): ...
    @pytest.mark.asyncio
    async def test_revoke_token_already_revoked_or_expired_is_ok(self): ...


# tests/test_auth_routes.py  (TestClient)
class TestAuthRoutes:
    def test_post_token_200(self): ...
    def test_post_token_401_identical_body_for_all_credential_failures(self): ...
    def test_post_token_400_expire_days_above_max(self): ...
    def test_post_token_422_expire_days_below_one(self): ...
    def test_post_revoke_200(self): ...
    def test_post_revoke_401_before_token_lookup(self): ...
    def test_post_revoke_404_unknown_or_foreign_token(self): ...
    def test_auth_routes_do_not_require_authorization_header(self): ...  # o middleware do /mcp não se aplica a /auth/*
    def test_login_failure_log_has_no_password_hash_or_email(self, caplog): ...
    def test_revoked_token_gets_401_on_mcp(self): ...


# tests/test_auth_middleware.py
class TestAuthMiddleware:
    def test_missing_header_returns_401(self): ...
    def test_malformed_header_returns_401(self): ...  # ex.: "Basic xxx", "Bearer" sem token
    def test_invalid_token_returns_401(self): ...
    def test_all_rejections_have_identical_response(self): ...  # status, WWW-Authenticate e corpo iguais nos 5 casos
    def test_valid_token_sets_contextvar_per_request(self): ...  # 2 requisições simultâneas, usuários distintos, sem mistura
    def test_contextvar_reset_after_request(self): ...  # contextvar volta ao default após a requisição, inclusive com exceção no handler
    def test_auth_failure_logs_reason_per_case(self, caplog): ...  # 1 WARNING com o reason correto em cada um dos 7 AuthFailureReason
    def test_auth_failure_log_never_contains_token_or_hash(self, caplog): ...  # nem token bruto, nem header, nem hash


# --- Testes EXISTENTES ajustados / ampliados (detalhe em §6.3) ---
# tests/test_mcp_tools.py            → 8 testes reescritos para list_tools(current_user)/call_tool(..., current_user)
# tests/test_server_setup.py         → TestStatelessTransport com Authorization; +401 sem header; +preflight CORS
# tests/test_execution_repo.py       → test_create_inserts_nine_columns... vira "ten_columns_with_user_id"
# tests/test_audit_service.py        → +user_id repassado ao repo (com e sem user_id)
# tests/test_analysis_service.py     → +execute(..., user_id=) repassado ao audit em todos os caminhos
# tests/test_config.py               → +ACCESS_TOKEN_EXPIRATION_DAYS/MAX (defaults e validação)


# tests/test_mcp_tools_auth.py
class TestMcpToolsAuth:
    @pytest.mark.asyncio
    async def test_call_tool_denies_before_cache_lookup(self): ...  # sem permissão → nem chega ao execute()/cache
    @pytest.mark.asyncio
    async def test_list_tools_filters_by_user_permission(self): ...
    @pytest.mark.asyncio
    async def test_list_tools_empty_when_no_profile(self): ...
    @pytest.mark.asyncio
    async def test_call_tool_revalidates_permission(self): ...
    @pytest.mark.asyncio
    async def test_call_tool_denies_when_permission_revoked_after_list(self): ...
    @pytest.mark.asyncio
    async def test_call_tool_logs_access_denied(self, caplog): ...
    @pytest.mark.asyncio
    async def test_call_tool_logs_user_id_in_execution_history(self): ...
```

### 6.2 Checklist de Testes
- [x] Unitário: `generate_token`/`hash_token`
- [x] Unitário: `verify_password` (correta, errada, hash nulo, senha > 72 bytes)
- [x] Unitário: `AuthService.authenticate` (sucesso, token não encontrado, expirado, revogado, usuário bloqueado/inexistente)
- [x] Unitário: `AuthService.issue_token` (padrão, `expire_days`/`label`, e-mail normalizado, acima do máximo, 4 falhas de credencial, token bruto nunca persistido)
- [x] Unitário: `AuthService.revoke_token` (sucesso, credenciais antes do token, token de outro usuário, já revogado/expirado)
- [x] Unitário: `AuthService.is_analysis_allowed` (permitido, sem perfil, perfil inativo, análise inativa)
- [x] Unitário: rotas `/auth/token` e `/auth/revoke` (200/400/401/404/422, sem exigir `Authorization`)
- [x] Unitário: middleware — 401 genérico e idêntico (ausente, malformado, inexistente, expirado, revogado, bloqueado) + `contextvar` isolado por requisição
- [x] Regressão: `contextvar` isolado entre usuários distintos no mesmo cliente, em sequência (`initialize` como A → `tools/list` como B chega como B) — falha se o transporte voltar a stateful
- [x] Unitário: `contextvar` restaurado (`reset`) ao fim de cada requisição, inclusive com exceção
- [x] Unitário: logs de falha (`/mcp`, login, acesso negado); nenhum contém token/header/hash/senha/`password_hash`/e-mail
- [x] Unitário: `list_tools()` filtra por permissão efetiva
- [x] Unitário: `call_tool()` revalida (nega mesmo após aparecer em `list_tools()`)
- [x] Unitário: `execution_history.user_id` gravado corretamente
- [x] Integração: `AnalysisRepository.get_allowed_for_user()` e `ProfileRepository.get_allowed_analysis_ids()` concordam (mesmo conjunto de analyses) para o mesmo usuário
- [x] Regressão: os 189 testes anteriores voltam a passar, com os 13 ajustados conforme §6.3
- [x] Integração: fluxo completo — `POST /auth/token` com usuário real → `tools/list` no `/mcp` com o token → `POST /auth/revoke` → `/mcp` passa a responder 401
- [x] Manual: testar via pelo menos 1 cliente MCP real com o token emitido por `/auth/token` no header `Authorization`
- [x] Manual: bloquear um usuário com sessão de cliente MCP já aberta e confirmar recusa imediata na próxima chamada

### 6.3 Impacto nos Testes Existentes

**Baseline:** 189 testes verdes (`pytest`, `asyncio_mode = strict`) antes do F12. **Esperado ao implementar o F12 sem ajustar testes:** 13 testes quebram — os 8 de `test_mcp_tools.py` (assinatura), os 4 de `TestStatelessTransport` (passam a receber 401 sem `Authorization`) e 1 de `test_execution_repo.py` (INSERT ganha `user_id`); os demais continuam passando. Regra de execução: **os testes são ajustados no mesmo passo em que o código correspondente muda** (não antes: mudar as assinaturas nos testes com o código ainda antigo deixaria a suíte vermelha), e a suíte inteira precisa voltar a 100% verde a cada passo.

| Arquivo | Impacto | Ajuste |
|---|---|---|
| `test_mcp_tools.py` (8) | **Quebra tudo:** `list_tools()`/`call_tool()` ganham `current_user`; `list_tools` passa a usar `get_allowed_analyses`; `call_tool` chama `is_analysis_allowed` e repassa `user_id` | Reescrever com `make_user()`: patch de `tools.analysis_service.get_allowed_analyses` (no lugar de `get_all_analyses`), patch de `tools.auth_service.is_analysis_allowed` (`AsyncMock(True)`), e `mock_execute.assert_awaited_once_with(analysis.id, args, False, user_id=user.id)`. Manter os cenários atuais (nome inválido, `confirmar_volume_alto`, análise inexistente/inativa, nunca lança). Nos casos "inexistente/inativa", afirmar que `is_analysis_allowed` **não** é chamado (a análise é resolvida antes da permissão) |
| `test_server_setup.py` (7 + 4 da stateless) | `/mcp` passa a exigir `Authorization`: os 4 `TestStatelessTransport` quebram; `test_mcp_route_no_redirect...` continua `!= 307`, mas o assert precisa virar `== 401` | Mover a fixture `client` para `conftest.py`; `_rpc()` envia `Authorization: Bearer test-token`, com `AuthService.authenticate` patchado (fixture `auth_headers`); `tools/list` patcha `get_allowed_analyses`; `tools/call` patcha `is_analysis_allowed`. Novos: sem header → 401 (incl. `initialize`) e sem `Mcp-Session-Id`; **preflight CORS (`OPTIONS /mcp` sem `Authorization`) responde sem 401** e o **401 carrega `access-control-allow-origin`** (o middleware de auth fica **dentro** do `CORSMiddleware` — sem isso, clientes Electron não fariam o preflight nem leriam o 401). `test_health` e o teste de CORS em `/health` não mudam (o middleware só envolve o `/mcp`). Novo: `test_contextvar_isolated_across_users_in_same_client` (§4.2 item 4b). Novo assert de que o 401 carrega `access-control-expose-headers` com `WWW-Authenticate` |
| `test_execution_repo.py` (2) | `test_create_inserts_nine_columns_without_version` **quebra** (afirma `$9`, nenhum `$10` e a lista exata de args) | Renomear para `..._ten_columns_with_user_id`: `$10` presente, `user_id` no fim dos args; novo teste com `user_id` omitido → `None` (linhas legadas/pré-F12 continuam gravando) |
| `test_audit_service.py` (8) | `log_execution` ganha `user_id` opcional — os testes atuais **continuam passando** | Adicionar: `user_id` repassado ao repo; omitido → `None`; e, no nível `AnalysisService` (mesmo arquivo), `execute(..., user_id=uid)` chega ao `log_execution` em sucesso, erro, `volume_exceeded` e **cache hit** — cache hit de outro usuário grava o `user_id` **de quem pediu**, não o de quem populou o cache |
| `test_analysis_service.py` (14) | `execute(..., user_id=None)` opcional; construtor **inalterado** — testes atuais passam | Adicionar `get_allowed_analyses` (delega ao repo com o `user_id`) |
| `test_cache_service.py` (24) | Nenhum. A chave do cache **não** inclui o usuário, e isso é seguro: `call_tool()` só chega ao `execute()` (e ao cache) depois de `is_analysis_allowed()`, então um usuário sem permissão nunca lê resultado cacheado por outro | Nenhum ajuste; a garantia é coberta por `test_call_tool_denies_before_cache_lookup` (`test_mcp_tools_auth.py`) |
| `test_config.py` (3) | Novos campos em `Settings` | Adicionar: defaults `ACCESS_TOKEN_EXPIRATION_DAYS=90` e `ACCESS_TOKEN_MAX_EXPIRATION_DAYS=365`; falha no startup (como `CACHE_BACKEND`) se algum for `< 1` ou se `EXPIRATION > MAX` (senão a emissão com o padrão já daria 400) |
| `test_adapter_*`, `test_mysql_adapter`, `test_postgresql_adapter`, `test_sqlserver_adapter`, `test_analysis_parameters`, `test_crypto`, `test_sql_validation`, `test_volume_guard_service` | Nenhum — não conhecem "usuário" | Nenhum |

**Infra de teste nova (`tests/conftest.py` e `tests/helpers.py`):**
- `make_user(name="Maria") -> AuthenticatedUser` (em `helpers.py`).
- Fixture **`client` de sessão** (uma só, movida de `test_server_setup.py`): o `session_manager.run()` só pode ser chamado **uma vez por processo**, então nenhum arquivo novo pode criar o próprio `TestClient(app)` com lifespan — quebraria. Continua exigindo o Config DB no ar, como o `test_health` já exige hoje.
- Fixtures **`auth_headers`** (patcha `AuthService.authenticate` para devolver um `AuthenticatedUser` fixo quando o token é `test-token`) e **`allow_all_analyses`** (patcha `is_analysis_allowed` → `True`).
- **Testes de rotas e de middleware não usam o app real:** `test_auth_routes.py` monta um `FastAPI()` mínimo com `include_router(auth_router)` e `app.dependency_overrides[get_auth_service]`; `test_auth_middleware.py` envolve um app ASGI de brinquedo com o middleware. Sem lifespan, sem banco, sem o limite do `session_manager` — e o teste de isolamento do `contextvar` (2 requisições simultâneas) fica determinístico.
- **Sem modo sem autenticação:** nenhum teste depende de `AUTH_ENABLED`; a autenticação é contornada só por essas fixtures.

**Validação manual do F6:** a validação multi-cliente (2+ clientes MCP simultâneos) continua ✅ como histórico, mas repeti-la depois do F12 exige um token por cliente, emitido por `POST /auth/token`; isso entra no manual da §6.2 e na F18.

## 7. Mudanças na Configuração

**Variáveis de Environment (.env):**
```
ACCESS_TOKEN_EXPIRATION_DAYS=90       # validade padrão de novos tokens, quando o request não traz expire_days
ACCESS_TOKEN_MAX_EXPIRATION_DAYS=365  # maior expire_days aceito em POST /auth/token (acima → 400)
```

**Dependências:** `bcrypt` (hash de senha) em `requirements.txt` — versão a fixar na implementação, conferindo wheel para o Python 3.13 do projeto. `secrets`/`hashlib` continuam da stdlib.

## 8. Documentação

### 8.1 Como a feature aparece no MCP
Não aparece como uma tool nova: é uma camada de autenticação em frente a `list_tools()`/`call_tool()`. O efeito visível para o usuário é que a lista de tools passa a variar por token/usuário. A emissão e a revogação de token são endpoints HTTP comuns (`/auth/token`, `/auth/revoke`), fora do protocolo MCP.

### 8.2 Como o usuário usa essa feature
**Admin (uma vez por usuário, SQL direto):**
1. Gera o hash bcrypt da senha do usuário, sem criar arquivo no projeto:
   ```
   python -c "import bcrypt, getpass; print(bcrypt.hashpw(getpass.getpass().encode(), bcrypt.gensalt()).decode())"
   ```
   (a senha é digitada sem eco; senhas acima de 72 bytes não são aceitas pelo bcrypt).
2. Cadastra o usuário: `INSERT INTO users (name, external_id, password_hash) VALUES ('Maria', 'maria@empresa.com', '<hash>')` — **e-mail sempre em minúsculas**.
3. Vincula o usuário a 1+ `profiles` via `user_profiles`, e cada perfil às `analyses` liberadas via `profile_analyses`.

**Usuário (sem admin):**
4. Emite o próprio token:
   ```
   curl -X POST https://<host>:3000/auth/token -H "Content-Type: application/json" \
        -d '{"email": "maria@empresa.com", "password": "...", "label": "Claude Desktop", "expire_days": 90}'
   ```
   `label` e `expire_days` são opcionais. O token aparece **uma única vez** na resposta.
5. Cola o token na configuração do cliente MCP (`Authorization: Bearer <token>`).
6. Quando o token expirar, repete o passo 4 e atualiza a config do cliente.
7. Para revogar um token (ex.: notebook perdido): `POST /auth/revoke` com `{"email", "password", "token"}`.

### 8.3 Como outros desenvolvedores estenderão isso
Um novo requisito de negócio (ex.: rate limiting por usuário — FB3) consome o mesmo `AuthenticatedUser` já resolvido em `list_tools()`/`call_tool()`, sem precisar reimplementar a autenticação. Proteção contra tentativas de senha em `/auth/token` (rate limit por IP/e-mail ou bloqueio por tentativas no banco) entra como middleware/serviço sobre `AuthService.issue_token()`, sem mudar o modelo de token. RBAC mais granular (ex.: permissão de leitura vs. escrita por analysis) estenderia `profile_analyses` com uma coluna de nível de acesso.

## 9. Checklist de Implementação

**Código:**
- [x] `security/token_auth.py`
- [x] `security/password_hash.py`
- [x] `schemas/auth.py`
- [x] `repositories/user_repo.py` (com `get_by_external_id`), `profile_repo.py`, `access_token_repo.py`
- [x] `services/auth_service.py` — `authenticate`, `issue_token`, `revoke_token`, `is_analysis_allowed`
- [x] `services/analysis_service.py` — `get_allowed_analyses()`, `execute(..., user_id=)`
- [x] `services/audit_service.py` / `repositories/execution_repo.py` — `user_id`
- [x] `security/auth_middleware.py` — middleware + `contextvar` + log de falhas (§4.5)
- [x] `routes/__init__.py` + `routes/auth.py` — `POST /auth/token`, `POST /auth/revoke`; registrar em `main.py` (`include_router`)
- [x] `mcp_transport/tools.py` — `list_tools()`/`call_tool()` exigem `AuthenticatedUser`; log `access_denied`
- [x] `database/schema.sql` (tabelas F12, `users.password_hash`, `execution_history.user_id`, índices) (migration para bancos existentes cancelada — F13)
- [x] `mcp_transport/tools.py` cria a instância única de `AuthService`; `routes/auth.py::get_auth_service()` e o middleware a reutilizam
- [x] `config.py` — `ACCESS_TOKEN_EXPIRATION_DAYS`, `ACCESS_TOKEN_MAX_EXPIRATION_DAYS`
- [x] `requirements.txt` — `bcrypt`
- [x] `repositories/analysis_repo.py` — `get_allowed_for_user()`
- [x] `tests/conftest.py` + `tests/helpers.py` (`make_user`) e ajuste dos 6 arquivos de teste existentes (§6.3), cada um no mesmo passo do código que o afeta
- [x] Testes (§6) passing — suíte inteira verde a cada passo
- [x] Docstrings

**QA:**
- [x] Code review aprovado
- [x] Validação manual com cliente MCP real (§6.2)
- [x] PR merge aprovado

---

## 10. Observações e Pendências (fora do escopo do F12)

| # | Observação | Situação |
|---|---|---|
| 1 | Sem CRUD/endpoint administrativo para `users`/`profiles`/vínculos — segue o padrão já usado para `analyses`/`data_sources` (INSERT direto, incluindo o hash bcrypt da senha) | Aceito em V1.0, consistente com o resto da plataforma |
| 2 | Sem tool MCP de auto-renovação de token — renovação é sempre manual (o usuário chama `POST /auth/token` de novo) | Decisão confirmada; pode virar backlog se o atrito for alto na prática |
| 3 | Threading do `AuthenticatedUser` do header HTTP até `list_tools()`/`call_tool()` | ✅ Resolvido: transporte stateless + middleware ASGI + `contextvar` — ver §4.2 |
| 4 | Identificação de qual cliente MCP/software está chamando (FB1) continua fora de escopo — `label` do token é só uma anotação informada pelo usuário, não uma identificação automática | Fora de escopo, ver FEATURES_ROADMAP.md §9 |
| 5 | Sem rate limiting/quota por usuário nas chamadas MCP (FB3) | Fora de escopo, backlog futuro |
| 6 | `execution_history.user_id` fica `NULL` para todas as linhas gravadas antes do F12 | Aceito — sem backfill retroativo |
| 7 | Falhas de autenticação/autorização só vão para o log (stdout), sem tabela de auditoria nem detecção/alerta; `client_ip` é o do socket (atrás de proxy reverso seria o IP do proxy — `X-Forwarded-For` de proxy confiável fica para a F13/Docker) | Aceito em V1.0; tabela de auditoria de falhas pode virar backlog se o log em stdout se mostrar insuficiente |
| 8 | **Sem proteção contra tentativas de senha em `POST /auth/token`/`/auth/revoke`** (sem rate limit, sem bloqueio por tentativas, sem atraso progressivo) — o bcrypt só encarece cada tentativa (~100 ms); quem alcançar o servidor pode testar senhas, e as falhas só aparecem no log | Decisão confirmada para V1.0 (rede interna, TLS); **rever antes de qualquer exposição fora da rede interna** (F13/deploy remoto) |
| 9 | O e-mail em `users.external_id` precisa ser cadastrado em minúsculas: a aplicação normaliza o e-mail recebido, mas não o valor gravado, e o banco não tem `CHECK` — um cadastro com maiúscula nunca casa com o login | Aceito; cuidado no INSERT manual |
| 10 | Sem troca/recuperação de senha nem endpoint de listagem de tokens: senha só muda por UPDATE direto de `password_hash`; tokens são revogados por `/auth/revoke` (o usuário precisa ter o token em mãos) | Aceito em V1.0 |
| 12 | Sem modo de desenvolvimento sem autenticação (`AUTH_ENABLED`): para rodar localmente é preciso cadastrar um usuário e emitir um token; os testes contornam a autenticação por fixtures | Decisão confirmada — evita uma flag que possa ir desligada para produção |
| 11 | Um token perdido, sem cópia guardada, não pode ser revogado por `/auth/revoke` (só por SQL, `UPDATE access_tokens SET revoked_at = NOW()`) — bloquear o usuário (`is_blocked`) também derruba todos os tokens dele | Aceito em V1.0 |
| 13 | O transporte stateless é **obrigatório** para o desenho de `contextvar` do F12 — voltar para stateful exige reescrever a leitura da identidade (ver §4.2 item 1 e ARQUITETURA.md ADR-006 v1.21). Consequência aceita: sem mensagens iniciadas pelo servidor (ex.: `tools/list_changed` quando um perfil muda); o cliente só vê a nova lista no próximo `list_tools()`, e `call_tool()` já revalida a permissão | Decisão confirmada (2026-09-30) |
| 14 | Comportamento dos clientes MCP reais com token estático: confirmar que Claude Desktop e ChatGPT Desktop permitem configurar `Authorization: Bearer` fixo num conector remoto e como reagem ao `401` com `WWW-Authenticate: Bearer` — pela especificação de autorização do MCP, alguns clientes podem tentar descoberta OAuth (`/.well-known/oauth-protected-resource`) em vez de usar o header. Se algum cliente não suportar header fixo, avaliar proxy local no cliente (ex.: `mcp-remote --header`) antes de mudar o desenho | ✅ Resolvido (2026-09-30): validado com Claude Desktop via `mcp-remote --header "Authorization:${AUTH_HEADER}"` (token em variável de ambiente do conector, ver §8.2) |

---

## 11. Implementação (2026-09-30)

**Resultado:** 295 testes ✅ (189 anteriores, com os 13 ajustados conforme §6.3, + 106 novos); 1 teste de integração (`tests/test_permission_queries_integration.py`) pula sozinho se a migration ainda não foi aplicada ao banco.

**Arquivos novos:** `security/{token_auth,password_hash,auth_middleware}.py`, `schemas/auth.py`, `repositories/{user,profile,access_token}_repo.py`, `services/auth_service.py`, `routes/{__init__,auth}.py`, `tests/{conftest,test_token_auth,test_password_hash,test_auth_service,test_auth_middleware,test_auth_routes,test_mcp_tools_auth,test_permission_queries_integration}.py`.

**Desvios em relação ao desenho acima (decididos na implementação):**
1. **O middleware envolve diretamente os endpoints do `/mcp`** (`add_route("/mcp", AuthMiddleware(...))` e `mount("/mcp", AuthMiddleware(...))`), sem filtro por path dentro dele. Tudo que chega ao middleware é `/mcp`; assim um path reescrito pelo `Mount` do Starlette nunca vira bypass de autenticação (fail-closed). `/health` e `/auth/*` nunca passam por ele; o `CORSMiddleware` continua mais externo.
2. **`AuthService.issue_token()` devolve `(token_bruto, expires_at, user_id, token_id)` e `revoke_token()` devolve `(user_id, token_id)`** (§4.4 previa `(token, expires_at)` e `None`): a rota precisa de `user_id`/`token_id` para o log INFO de §4.5 sem consultar o banco de novo.
3. **O middleware recebe um wrapper que resolve `tools.auth_service.authenticate` a cada chamada**, e não o bound method capturado em `configure_mcp()` — sem isso as fixtures de teste (§6.3) não conseguiriam patchar a autenticação depois do import.
4. **`_require_user()` em `mcp_transport/__init__.py`** levanta `PermissionError` se o contextvar estiver vazio: sem usuário no contexto (middleware ausente/contornado), nenhuma tool é listada nem executada (fail-closed).
5. **O SDK `mcp` chama `list_tools()` internamente em todo `tools/call`**, para validar o input contra o `inputSchema`. Consequência: uma query extra de permissão por `tools/call`, e os testes HTTP de `tools/call` precisam patchar `get_allowed_analyses`.
6. **Tempo constante no login:** `_validate_credentials()` sempre executa um `bcrypt.checkpw` — contra o hash real ou contra um hash fictício constante (custo 12) quando o e-mail não existe ou não tem senha —, para o tempo de resposta não revelar se o e-mail está cadastrado.
7. **`AccessTokenRepository.revoke()` é idempotente** (`WHERE revoked_at IS NULL`): revogar de novo mantém o `revoked_at` original.
8. **Config:** `Settings` valida no startup `ACCESS_TOKEN_EXPIRATION_DAYS >= 1`, `ACCESS_TOKEN_MAX_EXPIRATION_DAYS >= 1` e `EXPIRATION <= MAX`.

**Como rodar:** aplicar `database/schema.sql` → cadastrar usuário/perfil/vínculos por INSERT direto → `python run_https.py` → `POST /auth/token` → configurar o cliente (ver §8.2). Exemplo de conector Claude Desktop com `mcp-remote`:
```json
"analise-dados": {
  "command": "npx",
  "args": ["mcp-remote", "https://127.0.0.1:3000/mcp", "--header", "Authorization:${AUTH_HEADER}"],
  "env": {"NODE_OPTIONS": "--use-system-ca", "AUTH_HEADER": "Bearer <token>"}
}
```
(sem espaço depois de `Authorization:` — evita o problema de espaços em argumentos no Windows; o `Bearer ` vai dentro da variável.)

---

**Documento de Especificação F12 — Autenticação e Controle de Acesso via Perfis.**
**Sprint 3 — Production-Ready (F12 implementada em 2026-09-30).**
