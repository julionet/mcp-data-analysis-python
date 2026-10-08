# F23 — API Administrativa: Base + Usuários + Perfis + Autosserviço

## Feature Spec

**ID:** F23
**Nome:** API Administrativa — base (papel admin), usuários, perfis e autosserviço (`/me`)
**Prioridade:** 🟠 Alta
**Esforço Estimado:** 3.5d
**Status:** 🟩 Done (2026-10-08) — validação manual com cliente MCP real pendente (§6.3)

> **Origem dos requisitos:** NEGOCIO.md v1.12 (RF6, UC4, RNF5, Restrição T5), ARQUITETURA.md v1.26 (§2.4, §3.6, ADR-008), FEATURES_ROADMAP.md v1.22 e DATABASE_SCHEMA.md (`users.is_admin`, §2.6). Esta spec cobre só a **F23**; data sources e analyses são a F24 e o histórico de execuções é a F25.

---

## 1. Visão

Hoje usuários, perfis e seus vínculos só podem ser cadastrados por INSERT direto no Config DB, e não existe o conceito de administrador na aplicação (o "admin" do seed é só um perfil e um usuário). A F23 cria a base da API administrativa `/admin/*` — papel `users.is_admin`, autorização por token, convenções comuns — e entrega a gestão de **usuários** e **perfis**, mais o **autosserviço** `/me` (consultar os próprios dados e trocar a própria senha), para um futuro frontend de gestão.

## 2. Objetivo

Permitir que um administrador, autenticado pelo mesmo token da F12, crie/altere/exclua/pesquise usuários e perfis, redefina senhas, bloqueie usuários, vincule perfis e analyses e administre os tokens de cada usuário, sem acesso direto ao banco; e que qualquer usuário autenticado troque a própria senha.

**Métrica de Sucesso:**
- ✅ Toda rota `/admin/*` recusa chamada sem token válido (401) e de usuário sem `is_admin` (403) — verificado por teste parametrizado sobre **todas** as rotas
- ✅ `is_admin` e `is_blocked` são lidos do BD a cada chamada: bloquear um admin ou remover seu papel corta o acesso na chamada seguinte
- ✅ Senha de usuário só é gravada como hash bcrypt; nunca devolvida; política de senha aplicada nos três pontos de entrada
- ✅ `password_hash` e `token_hash` nunca aparecem em resposta nem em log
- ✅ Escritas multi-tabela são atômicas (transação com rollback testado)
- ✅ Exclusão física só sem dependentes (409 com histórico); último admin ativo e o próprio admin protegidos
- ✅ Os 500 testes atuais continuam passando; `/mcp` e `/auth/*` inalterados

## 3. Contexto

**Depende de:** F12 (Autenticação e Perfis — tabelas, `AuthService`, `AccessTokenRepository`), F14 (formato de erro de `/mcp` permanece separado)
**É dependência de:** F24 (Data Sources + Analyses) e F25 (Histórico), que reutilizam `require_admin`, paginação, `transaction()` e as convenções desta spec; F16 (documentação da API), F17 (cobertura)

**Já feito antes desta spec (2026-10-08):** coluna `users.is_admin BOOLEAN NOT NULL DEFAULT false` em `src/database/schema.sql` e `seed_admin.sh` marcando o usuário `admin` com `is_admin = true`. Bancos existentes precisam do `ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT false;` (manual — sem migrations).

**Estado do código (verificado antes de escrever):**
- Não existem: `require_admin`, `hash_password`, `PostgreSQLAdapter.transaction()`, `routes/admin_*`, `routes/me.py`, `services/*_admin_service.py`, `schemas/admin.py`; o CORS não permite `PUT`/`PATCH`; os repositórios de usuário, perfil e token só leem (exceto `AccessTokenRepository.create/touch_last_used/revoke`).
- `User` (`repositories/user_repo.py`) e `AuthenticatedUser` (`schemas/auth.py`) não têm `is_admin`.
- `PostgreSQLAdapter.execute()` devolve `None` (o status do asyncpg é descartado): para saber se algo foi afetado usa-se `UPDATE/INSERT ... RETURNING` via `execute_query`. Os placeholders `$n` são ligados à **ordem de inserção** dos valores do dict (`adapters/postgresql.py`).
- `_extract_bearer(scope)` (`security/auth_middleware.py`) opera sobre o `scope` ASGI e pode ser reutilizado com `request.scope`.
- Não há handler de `RequestValidationError`: o 422 sai no formato padrão do FastAPI (`{"detail": [...]}`), como em `/auth/*`.
- Não há política de senha (só o limite de 72 bytes, aplicado na verificação) nem validação de formato de e-mail; `email-validator` não está no `requirements.txt`.
- Os repositórios são instanciados dentro de `mcp_transport/tools.py` (só `auth_service` é exposto); `config_db_adapter` vem de `database/connection.py`.

---

## 4. Descrição Técnica

### 4.1 Componentes Afetados

```
Componentes criados/modificados:
├─ security/admin_auth.py          (novo) get_current_user(), require_admin()
├─ security/password_hash.py       (modificado) + hash_password(), + validate_password_policy()
├─ adapters/postgresql.py          (modificado) + transaction()
├─ repositories/user_repo.py       (modificado) User + is_admin; list/count/create/update/delete,
│                                   block, vínculos com perfis, contagem de admins ativos,
│                                   existência de execution_history
├─ repositories/profile_repo.py    (modificado) dataclass Profile; list/count/create/update/delete,
│                                   vínculos com analyses e usuários, detalhe
├─ repositories/access_token_repo.py (modificado) listagem por usuário (com last_used_at/created_at),
│                                   revogação por id, revogação de todos, contagem de ativos
├─ services/user_admin_service.py  (novo) regras de usuários, senha, tokens, proteções
├─ services/profile_admin_service.py (novo) regras de perfis e vínculos
├─ schemas/admin.py                (novo) modelos de request/response e exceções de domínio
├─ routes/dependencies.py          (novo) get_user_admin_service(), get_profile_admin_service()
├─ routes/admin_users.py           (novo) /admin/users
├─ routes/admin_profiles.py        (novo) /admin/profiles
├─ routes/me.py                    (novo) GET /me, PUT /me/password
├─ main.py                         (modificado) include_router dos três routers
├─ mcp_transport/__init__.py       (modificado) CORS: allow_methods + PUT, PATCH
└─ requirements.txt                (modificado) + email-validator (pydantic[email])
```

### 4.2 Autorização (ARQUITETURA.md §3.6)

As rotas `/admin/*` e `/me` ficam **fora** do `AuthMiddleware` (que envolve só o `/mcp`); portanto a autenticação é uma dependência FastAPI. O token é o mesmo da F12.

```python
# security/admin_auth.py (esboço)
async def get_current_user(request: Request, auth_service=Depends(get_auth_service)) -> AuthenticatedUser:
    try:
        raw = _extract_bearer(request.scope)            # reaproveita o parser do middleware
        return await auth_service.authenticate(raw)     # 401 se token/usuário inválido ou bloqueado
    except InvalidTokenError as exc:
        log auth_failed ...                              # mesmo formato do middleware
        raise HTTPException 401 {"error": "unauthorized", ...} + header WWW-Authenticate: Bearer

async def require_admin(user=Depends(get_current_user), users=Depends(get_user_repo)) -> AuthenticatedUser:
    record = await users.get_by_id(user.id)             # lê is_admin do BD a cada chamada
    if record is None or record.is_blocked or not record.is_admin:
        log admin_denied ...
        raise 403 {"error": "forbidden", ...}
    return user
```

- Cada router `/admin/*` é criado com `dependencies=[Depends(require_admin)]`; as rotas que precisam do ator (para as proteções de "próprio admin") também declaram `Depends(get_current_user)` (o FastAPI resolve a dependência uma vez por requisição).
- `/me` usa só `get_current_user` (qualquer usuário autenticado, não exige `is_admin`).
- **Fail-closed:** uma rota `/admin/*` sem `require_admin` ficaria pública. Por isso há um teste que percorre `app.routes` e exige 401 sem token e 403 com token de não-admin em **todas** as rotas com prefixo `/admin`.
- O 401 devolve a mesma mensagem genérica do `/mcp` (`TOKEN_ERROR_MESSAGE`), sem distinguir o motivo.
- `AuthenticatedUser` não muda; `User` ganha o campo `is_admin` (default `False`, para não quebrar os construtores existentes nos testes).

### 4.3 Convenções comuns (valem também para F24 e F25)

- **Prefixo e registro:** `/admin`, um router por recurso, `include_router` em `main.py` (como `routes/auth.py`).
- **Injeção:** serviços via `Depends(get_*_service)` em `routes/dependencies.py`, montando repositórios sobre `config_db_adapter` (sem importar `mcp_transport.tools`), para `dependency_overrides` nos testes.
- **Paginação (listagens):** `?limit=` (padrão 50, máximo 200, mínimo 1) e `?offset=` (padrão 0, mínimo 0); resposta `{"items": [...], "total": N, "limit": L, "offset": O}`; ordenação por nome (`ORDER BY name, id`). `total` conta com os mesmos filtros (duas consultas: `COUNT(*)` e página).
- **Busca `?q=`:** `ILIKE` por substring; os curingas `%` e `_` do termo são escapados.
- **Escritas:** `updated_at = NOW()` em toda alteração (não há triggers); e-mail normalizado `strip().lower()`; `UniqueViolationError` do asyncpg é traduzido para 409 mesmo depois da pré-checagem (corrida entre duas requisições).
- **Hash de senha:** `hash_password(password) -> str` (bcrypt, custo 12, executado em `asyncio.to_thread`, como a verificação); a política é validada antes (§4.4.1).
- **Transação:** `PostgreSQLAdapter.transaction()` — context manager assíncrono sobre `pool.acquire()` + `conn.transaction()` que entrega um objeto com `execute_query(query, params, scalar)` e `execute(query, *args)` com a mesma semântica do adapter. Os métodos dos repositórios aceitam um `db` opcional (o adapter ou a transação) e usam `self._db` por padrão.
- **Respostas:** nunca incluem `password_hash` nem `token_hash`. Os modelos de resposta tipam e-mail como `str` (não `EmailStr`) — o login `admin` do seed não é um e-mail válido e quebraria a serialização.
- **Log:** evento `admin_action actor_id=%s action=%s target_type=%s target_id=%s` (INFO) em toda escrita bem-sucedida; sem senha, hash, token nem e-mail.
- **Erros:** formato `{"error": "<slug>", "message": "..."}` (ADR-008), tabela na §4.5.

### 4.4 Endpoints

#### 4.4.1 Política de senha (usada em criar usuário, redefinir senha e `PUT /me/password`)

`validate_password_policy(password)` — decisão do responsável pelo projeto (2026-10-08):
- mínimo **6 caracteres**;
- ao menos **1 letra maiúscula**, **1 letra minúscula**, **1 número** e **1 caractere não alfanumérico**;
- máximo **72 bytes** em UTF-8 (limite técnico do bcrypt; acima disso o `verify_password` sempre recusa).

Violação → 400 `invalid_password`, com mensagem listando a regra violada. A política vale **só para gravação**; senhas já existentes (ex.: `Senh@123` do seed cumpre; outras gravadas à mão podem não cumprir) continuam podendo logar em `/auth/token`.

#### 4.4.2 Usuários — `/admin/users`

| Método | Path | Corpo / Query | Sucesso | Erros |
|---|---|---|---|---|
| GET | `/admin/users` | `q`, `is_blocked`, `profile_id`, `limit`, `offset` | 200 lista paginada de `UserSummary` | 401, 403 |
| POST | `/admin/users` | `{name, email, password, is_admin=false, profile_ids=[]}` | 201 `UserDetail` | 400 `invalid_password`, 409 `email_already_exists`, 422 (e-mail/ids), 422 `invalid_reference` |
| GET | `/admin/users/{id}` | — | 200 `UserDetail` | 404 `user_not_found` |
| PATCH | `/admin/users/{id}` | `{name?, email?, is_admin?}` (ao menos um campo) | 200 `UserDetail` | 404, 409 `email_already_exists`, 409 `self_protected`, 409 `last_admin_protected` |
| DELETE | `/admin/users/{id}` | — | 204 | 404, 409 `user_has_history`, 409 `self_protected`, 409 `last_admin_protected` |
| PUT | `/admin/users/{id}/password` | `{password}` | 204 | 404, 400 `invalid_password` |
| POST | `/admin/users/{id}/block` | — | 200 `UserDetail` | 404, 409 `self_protected`, 409 `last_admin_protected` |
| POST | `/admin/users/{id}/unblock` | — | 200 `UserDetail` | 404 |
| PUT | `/admin/users/{id}/profiles` | `{profile_ids}` (substitui o conjunto) | 200 `UserDetail` | 404, 422 `invalid_reference` |
| GET | `/admin/users/{id}/tokens` | — | 200 lista de `TokenInfo` | 404 |
| DELETE | `/admin/users/{id}/tokens/{token_id}` | — | 204 | 404 `user_not_found` / `token_not_found` |
| DELETE | `/admin/users/{id}/tokens` | — | 200 `{"revoked": N}` | 404 |

Modelos:
- `UserSummary`: `id, name, email, is_blocked, is_admin, created_at, updated_at`
- `UserDetail`: `UserSummary` + `created_by`, `profiles: [{id, name, is_active}]`, `active_tokens: int` (não revogados e não expirados)
- `TokenInfo`: `id, label, created_at, expires_at, revoked_at, last_used_at` (sem `token_hash`); a lista inclui tokens revogados e expirados
- `email` ← coluna `users.external_id`

Regras:
- **Criar:** `email` validado como `EmailStr` e normalizado; usuário e vínculos `user_profiles` gravados em **uma transação**; `created_by` = e-mail do admin autenticado (decisão 12).
- **Alterar:** só os campos enviados são gravados; se `email` não vier, o existente não é revalidado (o login `admin` do seed permanece intacto); `name` 1–255 caracteres.
- **Redefinir senha:** valida a política, grava o hash e **revoga todos os tokens do usuário** (`revoked_at = NOW()` onde ainda nulo) na mesma transação. O admin pode redefinir a própria senha por esta rota (decisão 2026-10-08) — isso revoga o token usado na chamada.
- **Bloquear/desbloquear:** só altera `is_blocked` (idempotente). Bloquear **não** revoga tokens — o bloqueio já corta o acesso a cada chamada (ADR-007).
- **Excluir:** em transação, recusa com 409 `user_has_history` se existir linha em `execution_history` do usuário (`SELECT 1 ... LIMIT 1`, há índice) — a mensagem orienta bloquear; o `DELETE` apaga em cascata `user_profiles` e `access_tokens`. Uma `ForeignKeyViolationError` por corrida também vira 409 `user_has_history`.
- **Substituir perfis:** valida que todos os `profile_ids` existem (senão 422 `invalid_reference` listando os ausentes); perfis inativos podem ser vinculados; `DELETE` + `INSERT` em transação.
- **Revogar tokens:** "revogar" = preencher `revoked_at` (não apaga a linha); revogar token já revogado é idempotente. O `token_id` precisa pertencer ao usuário da rota, senão 404 `token_not_found`.
- **Proteções (409):**
  - `self_protected`: o admin autenticado não pode bloquear, excluir nem remover o próprio `is_admin` por esta API.
  - `last_admin_protected`: a operação não pode deixar o sistema sem administrador ativo (`is_admin = true AND is_blocked = false`). Como o ator é sempre um admin ativo e a proteção anterior impede ato sobre si mesmo, esta regra só dispara em **corrida** entre dois administradores agindo um sobre o outro; é verificada dentro da transação, com `SELECT ... FOR UPDATE` nos administradores ativos.

#### 4.4.3 Perfis — `/admin/profiles`

| Método | Path | Corpo / Query | Sucesso | Erros |
|---|---|---|---|---|
| GET | `/admin/profiles` | `q`, `is_active`, `limit`, `offset` | 200 lista paginada de `ProfileSummary` | 401, 403 |
| POST | `/admin/profiles` | `{name, description?, is_active=true}` | 201 `ProfileDetail` | 409 `profile_name_already_exists` |
| GET | `/admin/profiles/{id}` | — | 200 `ProfileDetail` | 404 `profile_not_found` |
| PATCH | `/admin/profiles/{id}` | `{name?, description?, is_active?}` (ao menos um) | 200 `ProfileDetail` | 404, 409 `profile_name_already_exists` |
| DELETE | `/admin/profiles/{id}` | — | 204 | 404 |
| PUT | `/admin/profiles/{id}/analyses` | `{analysis_ids}` (substitui o conjunto) | 200 `ProfileDetail` | 404, 422 `invalid_reference` |
| PUT | `/admin/profiles/{id}/users` | `{user_ids}` (substitui o conjunto) | 200 `ProfileDetail` | 404, 422 `invalid_reference` |

Modelos:
- `ProfileSummary`: `id, name, description, is_active, users_count, analyses_count, created_at, updated_at`
- `ProfileDetail`: `ProfileSummary` + `users: [{id, name, email, is_blocked}]`, `analyses: [{id, name, is_active}]`

Regras:
- A listagem administrativa inclui perfis inativos e analyses inativas (diferente do `/mcp`).
- **Excluir:** sempre físico — `user_profiles` e `profile_analyses` têm `ON DELETE CASCADE`, nenhuma outra tabela referencia `profiles`. Efeito imediato: usuários perdem as analyses liberadas só por esse perfil (permissão recalculada a cada chamada, F12).
- **Substituir analyses/usuários:** valida a existência dos ids (`analyses`/`users`), `DELETE` + `INSERT` em transação; ids duplicados no corpo são tolerados (deduplicados).
- Desativar um perfil (`is_active=false`) não toca em `is_admin`: o papel administrativo é independente dos perfis (ADR-008).

#### 4.4.4 Autosserviço — `/me`

| Método | Path | Corpo | Sucesso | Erros |
|---|---|---|---|---|
| GET | `/me` | — | 200 `{id, name, email, is_admin, profiles: [{id, name, is_active}]}` | 401 |
| PUT | `/me/password` | `{current_password, new_password}` | 204 | 401, 400 `invalid_current_password`, 400 `invalid_password` |

- Exige só token válido (qualquer usuário autenticado, admin ou não).
- `PUT /me/password`: confere `current_password` com `verify_password` (em thread); valida a política em `new_password`; grava o hash e **revoga todos os tokens do usuário, inclusive o usado na chamada** (decisão 2026-10-08) — o cliente precisa emitir novo token em `POST /auth/token`.

### 4.5 Erros (formato `{"error": "<slug>", "message": "<texto em português>"}`)

| HTTP | `error` | Quando |
|---|---|---|
| 401 | `unauthorized` | Token ausente/malformado/inexistente/expirado/revogado; usuário bloqueado ou inexistente (mensagem genérica única; header `WWW-Authenticate: Bearer`) |
| 403 | `forbidden` | Autenticado, mas sem `is_admin` (ou admin bloqueado) |
| 404 | `user_not_found` · `profile_not_found` · `token_not_found` | Recurso inexistente (ou token que não é do usuário da rota) |
| 409 | `email_already_exists` · `profile_name_already_exists` | Violação de unicidade (`users.external_id`, `profiles.name`) |
| 409 | `user_has_history` | Exclusão de usuário com `execution_history` — usar bloquear |
| 409 | `self_protected` · `last_admin_protected` | Proteções da §4.4.2 |
| 400 | `invalid_password` · `invalid_current_password` | Política de senha violada · senha atual errada em `/me/password` |
| 422 | `invalid_reference` | Ids de perfil/análise/usuário inexistentes nos vínculos (lista os ausentes) |
| 422 | (padrão FastAPI `{"detail": [...]}`) | Corpo/query inválidos (e-mail mal formado, paginação fora dos limites, PATCH vazio) |
| 500 | `internal_error` | Handler global existente em `main.py` |

O contrato `error_code`/`retryable` da F14 continua restrito ao `/mcp` (ADR-008).

### 4.6 Banco de Dados

Sem DDL novo nesta feature: `users.is_admin` já consta de `schema.sql` e do `seed_admin.sh`. Bancos existentes: `ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT false;` (manual).

Índices: não são criados agora. `user_profiles(profile_id)` e `profile_analyses(analysis_id)` não existem além da PK composta; só serão criados se um `EXPLAIN` com volume realista justificar (mesmo critério da F15).

Consultas principais (todas parametrizadas `$n`):
- Listagem de usuários com filtro de perfil: `... WHERE ($1::text IS NULL OR name ILIKE ... OR external_id ILIKE ...) AND ($2::bool IS NULL OR is_blocked = $2) AND ($3::uuid IS NULL OR EXISTS (SELECT 1 FROM user_profiles up WHERE up.user_id = u.id AND up.profile_id = $3))`
- Administradores ativos: `SELECT id FROM users WHERE is_admin AND NOT is_blocked FOR UPDATE`
- Tokens ativos: `revoked_at IS NULL AND expires_at > NOW()`
- Revogar todos: `UPDATE access_tokens SET revoked_at = NOW() WHERE user_id = $1 AND revoked_at IS NULL RETURNING id`

### 4.7 Interfaces (assinaturas)

```python
# security/password_hash.py
class PasswordPolicyError(Exception): ...        # reason: str (regra violada)
def validate_password_policy(password: str) -> None: ...   # levanta PasswordPolicyError
async def hash_password(password: str) -> str: ...         # bcrypt custo 12, em thread

# adapters/postgresql.py
@asynccontextmanager
async def transaction(self) -> AsyncIterator["Transaction"]: ...

# services/user_admin_service.py
class UserAdminService:
    async def list_users(self, q, is_blocked, profile_id, limit, offset) -> Page[UserSummary]
    async def create_user(self, data: UserCreate, actor: AuthenticatedUser) -> UserDetail
    async def get_user(self, user_id: UUID) -> UserDetail
    async def update_user(self, user_id, data: UserUpdate, actor) -> UserDetail
    async def delete_user(self, user_id, actor) -> None
    async def reset_password(self, user_id, password: str, actor) -> None
    async def set_blocked(self, user_id, blocked: bool, actor) -> UserDetail
    async def set_profiles(self, user_id, profile_ids: list[UUID], actor) -> UserDetail
    async def list_tokens(self, user_id) -> list[TokenInfo]
    async def revoke_token(self, user_id, token_id, actor) -> None
    async def revoke_all_tokens(self, user_id, actor) -> int
    async def get_me(self, user: AuthenticatedUser) -> Me
    async def change_own_password(self, user, current_password, new_password) -> None

# services/profile_admin_service.py
class ProfileAdminService:
    async def list_profiles(self, q, is_active, limit, offset) -> Page[ProfileSummary]
    async def create_profile(self, data: ProfileCreate, actor) -> ProfileDetail
    async def get_profile(self, profile_id) -> ProfileDetail
    async def update_profile(self, profile_id, data: ProfileUpdate, actor) -> ProfileDetail
    async def delete_profile(self, profile_id, actor) -> None
    async def set_analyses(self, profile_id, analysis_ids, actor) -> ProfileDetail
    async def set_users(self, profile_id, user_ids, actor) -> ProfileDetail
```

As exceções de domínio (`UserNotFoundError`, `EmailAlreadyExistsError`, `SelfProtectedError`, ...) ficam em `schemas/admin.py`, e as rotas as traduzem para o formato de erro da §4.5 (padrão de `routes/auth.py`).

---

## 5. Critérios de Aceitação

```gherkin
Feature: API administrativa — usuários, perfis e autosserviço

Scenario: Acesso sem token
  Given Nenhum header Authorization
  When Chamo qualquer rota /admin/* ou /me
  Then Recebo 401 {"error":"unauthorized"} com WWW-Authenticate: Bearer

Scenario: Usuário comum não acessa /admin
  Given Um usuário autenticado com is_admin=false
  When Chamo qualquer rota /admin/*
  Then Recebo 403 {"error":"forbidden"} e nada é lido nem alterado

Scenario: Papel lido do banco a cada chamada
  Given Um admin com token válido
  When Outro admin remove o is_admin dele (ou o bloqueia)
  Then A chamada seguinte do primeiro recebe 403 (ou 401) mesmo com o mesmo token

Scenario: Criar usuário com perfis
  Given Um admin autenticado e o perfil "Comercial" existente
  When POST /admin/users {name, email válido, senha dentro da política, profile_ids:["<Comercial>"]}
  Then Recebo 201 com o usuário e o perfil vinculado, sem password_hash
  And O usuário consegue emitir token em POST /auth/token com essa senha

Scenario: Senha fora da política
  When Crio usuário, redefino senha ou troco a própria senha com "abc123" (sem maiúscula e sem símbolo)
  Then Recebo 400 invalid_password e nada é gravado

Scenario: E-mail duplicado ou inválido
  When Crio ou altero usuário com e-mail já usado (qualquer caixa)
  Then Recebo 409 email_already_exists
  When Envio um e-mail mal formado
  Then Recebo 422 e nada é gravado

Scenario: Login "admin" do seed continua listável
  Given O usuário seed com external_id "admin" (não é e-mail válido)
  When GET /admin/users e GET /admin/users/{id}
  Then Recebo 200 com email "admin" (sem erro de serialização)
  When PATCH /admin/users/{id} {"name":"Outro"} sem enviar email
  Then O login "admin" permanece e nenhum erro de validação de e-mail ocorre

Scenario: Redefinir senha revoga os tokens
  Given Um usuário com 2 tokens ativos
  When O admin faz PUT /admin/users/{id}/password com senha válida
  Then Recebo 204, os 2 tokens passam a ter revoked_at e os próximos /mcp com eles recebem 401

Scenario: Admin redefine a própria senha
  When O admin faz PUT /admin/users/{próprio id}/password
  Then Recebo 204 e o token usado na chamada fica revogado

Scenario: Bloquear usuário
  When POST /admin/users/{id}/block
  Then is_blocked=true e a próxima chamada /mcp dele recebe 401, sem revogar tokens
  When POST /admin/users/{id}/unblock
  Then ele volta a acessar com o mesmo token

Scenario: Proteções do administrador
  When Um admin tenta bloquear, excluir ou remover o próprio is_admin
  Then Recebo 409 self_protected
  When Duas requisições concorrentes tentam deixar o sistema sem admin ativo
  Then Uma delas recebe 409 last_admin_protected

Scenario: Excluir usuário
  Given Um usuário sem execution_history
  When DELETE /admin/users/{id}
  Then Recebo 204 e seus vínculos e tokens somem em cascata
  Given Um usuário com execution_history
  When DELETE /admin/users/{id}
  Then Recebo 409 user_has_history orientando a bloquear

Scenario: Gestão de tokens de um usuário
  When GET /admin/users/{id}/tokens
  Then Recebo id, label, datas e last_used_at, nunca token_hash
  When DELETE /admin/users/{id}/tokens/{token_id} de outro usuário
  Then Recebo 404 token_not_found

Scenario: Perfis e vínculos
  When Crio o perfil "Financeiro", vinculo analyses e usuários (PUT .../analyses, PUT .../users)
  Then O usuário vinculado passa a ver essas analyses em list_tools() imediatamente
  When Envio um id de análise inexistente
  Then Recebo 422 invalid_reference listando o id e nada é gravado (rollback)

Scenario: Excluir perfil
  When DELETE /admin/profiles/{id}
  Then Recebo 204 e os vínculos com usuários e analyses somem; usuários perdem o acesso concedido só por ele

Scenario: Autosserviço
  When GET /me com token de um usuário comum
  Then Recebo 200 com meus dados e perfis
  When PUT /me/password com senha atual errada
  Then Recebo 400 invalid_current_password
  When PUT /me/password com senha atual correta e nova dentro da política
  Then Recebo 204 e todos os meus tokens ficam revogados

Scenario: CORS para um frontend
  When O navegador envia preflight OPTIONS com Access-Control-Request-Method: PUT ou PATCH
  Then A resposta permite o método
```

---

## 6. Testes

### 6.1 Testes Unitários / de Rota

Padrão de `tests/test_auth_routes.py`: FastAPI mínimo com `include_router` + `app.dependency_overrides`, repositórios fake em memória, bcrypt com `rounds=4` nos fakes, sem lifespan nem banco.

```python
class TestAdminAuthorization:
    @pytest.mark.parametrize("route", ALL_ADMIN_ROUTES)   # gerado de app.routes com prefixo /admin
    def test_no_token_returns_401(self, route): ...
    @pytest.mark.parametrize("route", ALL_ADMIN_ROUTES)
    def test_non_admin_returns_403(self, route): ...
    def test_admin_blocked_or_demoted_loses_access(self): ...
    def test_me_accepts_non_admin(self): ...

class TestPasswordPolicy:
    # mínimo 6, maiúscula, minúscula, número, não alfanumérico, máximo 72 bytes; acentos; limites
class TestHashPassword:
    # hash verificável por verify_password; custo 12; senha > 72 bytes recusada

class TestUsersRoutes:   # list/filtros/paginação, create (+vínculos), get, patch parcial, delete,
                         # reset_password (revoga tokens), block/unblock, set_profiles, tokens
class TestUserProtections:   # self_protected, last_admin_protected, user_has_history
class TestProfilesRoutes:    # CRUD, set_analyses/set_users, invalid_reference, cascata
class TestMeRoutes:          # GET /me, PUT /me/password (atual errada, política, revoga todos)
class TestSerialization:     # login "admin" sem @ em GET/PATCH; nunca password_hash/token_hash no corpo
class TestNoSecretsInLogs:   # caplog: sem senha, hash, token nem e-mail em admin_action/auth_failed
class TestCors:              # preflight PUT/PATCH em /admin/*
class TestTransaction:       # PostgreSQLAdapter.transaction(): commit, rollback na exceção
```

### 6.2 Integração (Config DB real)

Arquivo no padrão de `tests/test_permission_queries_integration.py` (fixture `db` que dá `pytest.skip` se as tabelas da F12 ou a coluna `is_admin` não existirem): rollback real em `create_user` com perfil inexistente, cascatas de `DELETE` (usuário, perfil), `FOR UPDATE` dos administradores ativos, unicidade (`UniqueViolationError` → 409), efeito imediato de vínculos em `get_allowed_analysis_ids`.

### 6.3 Checklist de Testes
- [x] 401/403 em **todas** as rotas `/admin/*` (parametrizado por `app.routes`)
- [x] Papel e bloqueio lidos do banco a cada chamada
- [x] Política de senha nos três pontos de entrada
- [x] Hash de senha: custo 12, verificável, > 72 bytes recusado
- [x] CRUD de usuários e perfis, filtros e paginação
- [x] Redefinição de senha e `/me/password` revogam tokens
- [x] Proteções: próprio admin, último admin ativo, usuário com histórico
- [x] `invalid_reference` com rollback completo
- [x] Login `admin` do seed serializa sem erro; PATCH sem e-mail não revalida
- [x] Nenhum segredo (senha, hash, token) em respostas nem em logs
- [x] `transaction()` commit/rollback; integração com banco real
- [x] CORS permite PUT/PATCH; `/mcp` e `/auth/*` inalterados (regressão dos 500 testes)
- [ ] Manual: criar usuário e perfil pela API, vincular análise, emitir token do novo usuário e ver só a análise liberada no cliente MCP; bloquear → perde acesso imediato (spec F12/ADR-007)

---

## 7. Mudanças na Configuração

Sem variáveis novas no `.env`. Mudanças de ambiente:
- `requirements.txt`: adicionar `email-validator` (ou `pydantic[email]`) — a imagem Docker precisa ser reconstruída (`docker compose ... up -d --build`).
- Bancos existentes: `ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT false;` e reexecutar o seed (`setup-admin.ps1`/`.sh`) para marcar o admin.

## 8. Documentação

### 8.1 Como a feature aparece no MCP
Não aparece: é API HTTP separada do `/mcp`. Efeitos indiretos: vínculos usuário↔perfil↔análise e bloqueios feitos por esta API valem imediatamente em `list_tools()`/`call_tool()` (sem cache de permissão).

### 8.2 Como o usuário usa
O frontend (fora de escopo) chama `POST /auth/token` com o e-mail e a senha de um administrador e usa o token em `Authorization: Bearer` nas rotas `/admin/*`; qualquer usuário usa `/me`. O primeiro administrador vem do seed (`setup-admin`).

### 8.3 Como outros desenvolvedores estenderão
F24 e F25 criam novos routers com `dependencies=[Depends(require_admin)]`, reutilizam paginação, `transaction()`, o formato de erro e o evento `admin_action`.

---

## 9. Checklist de Implementação

**Código:**
- [x] `hash_password` + `validate_password_policy` + `PasswordPolicyError`
- [x] `PostgreSQLAdapter.transaction()`
- [x] `User.is_admin` + novos métodos nos 3 repositórios (com `db` opcional)
- [x] `security/admin_auth.py` (`get_current_user`, `require_admin`)
- [x] `schemas/admin.py` (modelos + exceções)
- [x] `services/user_admin_service.py`, `services/profile_admin_service.py`
- [x] `routes/dependencies.py`, `routes/admin_users.py`, `routes/admin_profiles.py`, `routes/me.py`
- [x] `main.py` (include_router) e CORS (`PUT`, `PATCH`)
- [x] `requirements.txt` (email-validator)
- [x] Docstrings

**Documentação (ao concluir):**
- [x] Preencher §12; marcar F23 como 🟩 no ROADMAP e no `.claude/CLAUDE.md`
- [x] ARQUITETURA.md §2.4/§3.6: trocar "slugs definidos na spec" pelos slugs da §4.5; DATABASE_SCHEMA.md se houver índice novo

**QA:**
- [x] Suíte completa passando (com `.venv`)
- [ ] Validação manual com cliente MCP real (§6.3)
- [ ] Code review

---

## 10. Decisões desta sessão (2026-10-08)

| # | Decisão |
|---|---|
| 1 | Papel administrativo por coluna `users.is_admin`, lido do BD a cada chamada; `require_admin` aplicado no router (rotas `/admin/*` ficam fora do `AuthMiddleware`) — ADR-008 |
| 2 | Erros no formato `{"error","message"}` das rotas `/auth/*`; contrato da F14 só no `/mcp` — ADR-008 |
| 3 | `DELETE` híbrido: físico só sem dependentes; vínculos N:N e tokens apagam em cascata — ADR-008 |
| 4 | Política de senha (criar, redefinir, `/me/password`): mínimo 6 caracteres, ≥ 1 maiúscula, ≥ 1 minúscula, ≥ 1 número, ≥ 1 caractere não alfanumérico; máximo 72 bytes (limite do bcrypt) |
| 5 | E-mail validado com `EmailStr` (nova dependência `email-validator`) em criação/alteração; respostas tipam e-mail como `str` porque o login `admin` do seed não é e-mail válido |
| 6 | O admin pode redefinir a própria senha por `PUT /admin/users/{id}/password` (revoga todos os seus tokens, inclusive o usado) |
| 7 | `PUT /me/password` revoga **todos** os tokens do usuário, inclusive o usado na chamada |
| 8 | Proteções: o admin autenticado não bloqueia/exclui/rebaixa a si mesmo (`self_protected`); o último admin ativo não pode ser removido (`last_admin_protected`, verificado em transação) |
| 9 | Bloquear usuário não revoga tokens (o bloqueio já corta o acesso); redefinir senha revoga |
| 10 | Serviços injetados por `routes/dependencies.py` sobre `config_db_adapter`, sem importar `mcp_transport.tools` |
| 11 | Repositórios aceitam um `db` opcional (adapter ou transação) em vez de abrir transação internamente |
| 12 | `users.created_by` ao criar pela API = e-mail (`external_id`) do administrador autenticado que criou |
| 13 | Ids inexistentes em `PUT .../profiles`, `.../analyses`, `.../users` → 422 `invalid_reference` listando os ids ausentes; nada é gravado |
| 14 | Paginação: `limit` padrão 50 (máximo 200) |
| 15 | O 422 de validação do FastAPI mantém o formato padrão `{"detail":[...]}` (como `/auth/*`), sem handler novo |
| 16 | Senha atual errada em `PUT /me/password` → 400 `invalid_current_password` (não 401, para o frontend não confundir com token expirado) |
| 17 | Na política de senha, espaço não conta como caractere não alfanumérico: exige símbolo/pontuação (qualquer caractere que não seja letra, dígito nem espaço); letras acentuadas contam como letra |
| 18 | `PATCH` sem nenhum campo → 422 (o corpo precisa de ao menos um campo) |

**Observações e pendências (fora do escopo):**

| # | Observação |
|---|---|
| 1 | Sem tabela de auditoria das ações administrativas (só o log `admin_action`) |
| 2 | Sem rate limit nem bloqueio por tentativas de senha (pendência herdada da F12/ADR-007) |
| 3 | Sem papéis administrativos granulares (ex.: auditor somente leitura) |
| 4 | Sem reset de senha por e-mail (reset só por admin ou pelo próprio usuário com a senha atual) |
| 5 | Mudar o `external_id` (login) de um usuário não revoga os tokens existentes |
| 6 | Formato de erro 422 do FastAPI não é convertido para o slug (mesma situação de `/auth/*`) |

## 11. Pontos em aberto

Nenhum. Os 7 pontos levantados na escrita da spec foram confirmados pelo responsável em 2026-10-08 e passaram para a §10 (decisões 12 a 18):

| # | Ponto | Resolução |
|---|---|---|
| ~~1~~ | Valor de `users.created_by` ao criar pela API | ✅ E-mail do usuário que criou (decisão 12) |
| ~~2~~ | Ids inexistentes nos vínculos | ✅ 422 `invalid_reference` (decisão 13) |
| ~~3~~ | Tamanho de página padrão | ✅ 50, máximo 200 (decisão 14) |
| ~~4~~ | Formato do 422 do FastAPI | ✅ Mantém o padrão (decisão 15) |
| ~~5~~ | Senha atual errada em `PUT /me/password` | ✅ 400 `invalid_current_password` (decisão 16) |
| ~~6~~ | Espaço na política de senha | ✅ Não conta como não alfanumérico (decisão 17) |
| ~~7~~ | `PATCH` sem nenhum campo | ✅ 422 (decisão 18) |

## 12. Implementação

**Resultado (2026-10-08):** 571/571 testes ✅ com `.venv` (500 anteriores + 71 novos: 65 de rota/serviço em `tests/test_admin_api.py` com repositórios em memória de `tests/admin_fakes.py`, 6 de integração em `tests/test_admin_integration.py` contra um Postgres 18 real com o `schema.sql`; a integração pula sozinha sem banco ou sem `users.is_admin`).

**Arquivos novos:** `security/admin_auth.py`, `schemas/admin.py`, `services/user_admin_service.py`, `services/profile_admin_service.py`, `routes/{dependencies,admin_route,admin_users,admin_profiles,me}.py`, `repositories/sql_helpers.py`. **Modificados:** `security/password_hash.py`, `adapters/postgresql.py` (`Transaction` + `transaction()`), os três repositórios, `main.py`, CORS (`PUT`/`PATCH`), `requirements.txt` (`email-validator`).

**Desvios em relação ao desenho:**
- Tradução de erros por `AdminRoute` (`route_class` dos routers), não por handlers no app: assim funciona em apps de teste montados só com `include_router`, e cobre também o 401/403 levantado pelas dependências. Todas as exceções de domínio herdam de `AdminError` (status + slug).
- O teste de "todas as rotas `/admin/*`" percorre `app.openapi()["paths"]`: no FastAPI 0.142 `app.routes` guarda os routers incluídos num wrapper (`_IncludedRouter`), não em `APIRoute`.
- `last_admin_protected` só é reproduzível por corrida; o teste unitário simula-a trocando `lock_active_admin_ids`, e o de integração só roda se não houver outros admins ativos no banco.
- `PATCH` com `name`/`is_active` = `null` é tratado como "não enviado" (colunas `NOT NULL`); `description: null` limpa o campo.

**Como rodar:** `.venv/bin/python -m pytest tests` (a integração e os testes do app real usam o Config DB do `.env`, `localhost:5433`). Bancos existentes: `ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT false;`; reconstruir a imagem Docker (nova dependência).
