# [F12] Autenticação e Controle de Acesso via Perfis

## Feature Spec

**ID:** F12
**Nome:** Autenticação e Controle de Acesso via Perfis
**Prioridade:** 🔴 Crítica
**Esforço Estimado:** 2.5d (20h)
**Status:** ⬜ Todo

---

## 1. Visão

Restringe `list_tools()`/`call_tool()` a usuários autenticados por token de acesso, e a quais analyses cada usuário pode ver/executar via um modelo de **perfis** (usuário N:N perfil N:N analyses). Substitui o modelo "rede interna confiável, sem autenticação" de V1.0 por um controle de acesso explícito, sem introduzir OAuth2/SSO nem exigir login/senha no servidor.

## 2. Objetivo

Garantir que cada chamada MCP seja de um usuário identificado, não bloqueado, e que só enxergue/execute analyses ativas vinculadas a um perfil ativo vinculado a ele — com bloqueio de usuário e mudança de permissão tendo efeito **imediato**, sem depender de expiração de token.

**Métrica de Sucesso:**
- ✅ Chamada MCP sem `Authorization` header, ou com token inválido/expirado/revogado, é recusada antes de qualquer consulta de negócio
- ✅ Usuário bloqueado (`is_blocked=true`) perde acesso imediatamente, mesmo com token não expirado
- ✅ `list_tools()` retorna somente analyses ativas vinculadas a um perfil ativo vinculado ao usuário autenticado
- ✅ `call_tool()` revalida a permissão — nunca confia apenas no que `list_tools()` já mostrou
- ✅ `execution_history` registra `user_id` de quem executou
- ✅ `scripts/generate_access_token.py` emite um token opaco válido, sem endpoint de login no servidor

## 3. Contexto

**Depende de:**
- F5 (MCP Tools Integration) — `list_tools()`/`call_tool()` já existentes em `mcp_transport/tools.py`, ponto de integração do auth ✅
- F8 (Log de Execução) — `AuditService.log_execution()`/`execution_history` já existentes, ganham `user_id` ✅

**É dependência de:**
- F13 (Docker Setup) — imagem de produção interna já deve sair com autenticação obrigatória
- F17 (Unit Tests) — cobertura de `AuthService`/`token_auth.py`
- F18 (Integration Tests) — cenário multi-cliente passa a incluir tokens distintos por cliente

**Decisões confirmadas (sessão de 2026-09-28/29 — ver ARQUITETURA.md ADR-007 para o racional completo):**
- Token **opaco** (`secrets.token_urlsafe(32)`, hash SHA-256 persistido) — não JWT, não OAuth2
- Emissão **administrativa** via script local (`scripts/generate_access_token.py`) — sem endpoint de login/senha no servidor
- **N tokens por usuário** (1 por cliente MCP), identificados por `label`
- Expiração padrão **90 dias** (`ACCESS_TOKEN_EXPIRATION_DAYS` via `.env`)
- Renovação **manual** — reemissão do script quando o token expira, sem tool de auto-renovação
- Permissão (usuário → perfil → analyses) é **recalculada a cada chamada**, nunca cacheada no token
- `execution_history` ganha `user_id` (nullable) — quem executou cada análise

---

## 4. Descrição Técnica

### 4.1 Componentes Afetados

```
Componentes novos:
├─ security/token_auth.py            # generate_token(), hash_token()
├─ services/auth_service.py          # AuthService.authenticate(), is_analysis_allowed()
├─ repositories/user_repo.py         # UserRepository
├─ repositories/profile_repo.py      # ProfileRepository (get_allowed_analysis_ids)
├─ repositories/access_token_repo.py # AccessTokenRepository
├─ schemas/auth.py                   # AuthenticatedUser, InvalidTokenError
├─ scripts/generate_access_token.py  # emissão administrativa de token (padrão de encrypt_credential.py)
├─ tests/test_token_auth.py
├─ tests/test_auth_service.py
└─ tests/test_mcp_tools_auth.py      # list_tools()/call_tool() com AuthenticatedUser

Componentes modificados:
├─ mcp_transport/tools.py            # list_tools()/call_tool() exigem AuthenticatedUser (ver §4.2, nota técnica)
├─ services/analysis_service.py      # get_allowed_analyses(user_id); execute(..., user_id=) repassado ao Audit
├─ services/audit_service.py         # log_execution(..., user_id=)
├─ repositories/execution_repo.py    # grava execution_history.user_id
├─ database/models.py                # SQLAlchemy models: User, Profile, UserProfile, ProfileAnalysis, AccessToken
├─ database/migrations/versions/     # nova migration Alembic (tabelas F12 + execution_history.user_id)
├─ config.py                         # ACCESS_TOKEN_EXPIRATION_DAYS (default 90)
└─ .spec/{NEGOCIO,ARQUITETURA,DATABASE_SCHEMA,FEATURES_ROADMAP}.md — já atualizados nesta revisão

Sem mudança:
├─ adapters/*, VolumeGuardService, CacheService — nenhum dos dois conhece "usuário"
└─ Schema de data_sources/analyses/analysis_steps (analyses.parameters não muda)
```

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
        └─ SELECT DISTINCT a.* FROM analyses a
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

**Emissão de token (fora do fluxo MCP, administrativa):**
```
python scripts/generate_access_token.py --user-id <uuid> --label "Claude Desktop - notebook Julio" --expires-days 90
  ├─ token = generate_token()  # secrets.token_urlsafe(32)
  ├─ AccessTokenRepository.create(user_id, hash_token(token), expires_at, label)
  └─ Imprime o token bruto 1 única vez — nunca fica salvo em texto puro
```

**Nota técnica em aberto (a resolver na implementação, não muda nenhuma decisão de negócio):**
O SDK `mcp` usado neste projeto (`mcp>=1.9.0,<2.0.0`, classe de baixo nível `Server`, ver ADR-006) registra `list_tools()`/`call_tool()` como decorators sem um parâmetro de `Request` HTTP direto. Como F12 precisa extrair e validar o header `Authorization` por requisição e entregar o `AuthenticatedUser` resultante dentro desses handlers, é necessário confirmar durante a implementação **como** threadar esse contexto — candidatos: (a) middleware ASGI que valida o token e guarda o `AuthenticatedUser` num `contextvar`, lido dentro de `list_tools()`/`call_tool()`; (b) mecanismo de contexto por requisição já exposto pelo SDK `mcp` (a confirmar na documentação/código da versão travada). Isso é detalhe de implementação de `mcp_transport/tools.py`, não uma decisão de arquitetura em aberto.

### 4.3 Banco de Dados

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    external_id VARCHAR(255) UNIQUE,
    is_blocked BOOLEAN DEFAULT false,
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT true,
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
    expires_at TIMESTAMP NOT NULL,
    revoked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP
);

ALTER TABLE execution_history ADD COLUMN user_id UUID REFERENCES users(id);

CREATE INDEX idx_access_tokens_hash ON access_tokens(token_hash);
CREATE INDEX idx_access_tokens_user ON access_tokens(user_id);
CREATE INDEX idx_execution_history_user ON execution_history(user_id);
```

Ver DATABASE_SCHEMA.md §2.6-§2.10 para a descrição campo a campo, e ARQUITETURA.md §2.2 para o schema completo em ordem de criação.

**Cadastro de usuários/perfis/vínculos:** segue o mesmo padrão já usado para `analyses`/`data_sources` (UC1 em NEGOCIO.md) — `INSERT` direto nas tabelas, sem CRUD/endpoint dedicado. Nenhuma interface administrativa é criada nesta feature (ver §10, Observações).

### 4.4 Endpoints/Interfaces

```python
# security/token_auth.py
def generate_token() -> str:
    """secrets.token_urlsafe(32)."""

def hash_token(raw_token: str) -> str:
    """SHA-256 hex do token bruto."""


# schemas/auth.py
@dataclass
class AuthenticatedUser:
    id: UUID
    name: str

class InvalidTokenError(Exception):
    """Token ausente, inválido, expirado, revogado, ou usuário bloqueado/inexistente."""


# repositories/access_token_repo.py
class AccessTokenRepository:
    async def get_by_hash(self, token_hash: str) -> AccessToken | None: ...
    async def create(self, user_id: UUID, token_hash: str, expires_at: datetime, label: str | None) -> AccessToken: ...
    async def touch_last_used(self, token_id: UUID) -> None: ...
    async def revoke(self, token_id: UUID) -> None: ...


# repositories/user_repo.py
class UserRepository:
    async def get_by_id(self, user_id: UUID) -> User | None: ...


# repositories/profile_repo.py
class ProfileRepository:
    async def get_allowed_analysis_ids(self, user_id: UUID) -> set[UUID]:
        """JOIN profile_analyses + user_profiles + profiles (is_active=true).
        Não filtra analyses.is_active — isso é responsabilidade de quem
        cruza o resultado com AnalysisRepository (ver AnalysisService)."""


# services/auth_service.py
class AuthService:
    def __init__(self, token_repo: AccessTokenRepository, user_repo: UserRepository, profile_repo: ProfileRepository):
        ...

    async def authenticate(self, raw_token: str) -> AuthenticatedUser:
        """Levanta InvalidTokenError se token ausente/inválido/expirado/revogado
        ou usuário inexistente/bloqueado. Nunca lança para "análise não permitida"
        — isso é is_analysis_allowed(), chamado depois, já com o usuário resolvido."""

    async def is_analysis_allowed(self, user_id: UUID, analysis_id: UUID) -> bool:
        """Reconsulta get_allowed_analysis_ids(user_id) — sem cache. Usado tanto
        por list_tools() (implicitamente, via AnalysisService.get_allowed_analyses)
        quanto por call_tool() (explicitamente, na revalidação)."""


# services/analysis_service.py (modificado)
async def get_allowed_analyses(self, user_id: UUID) -> list[Analysis]:
    """get_all_analyses() já existente, filtrado pela interseção com
    ProfileRepository.get_allowed_analysis_ids(user_id)."""

async def execute(self, analysis_id: UUID, params: dict, confirmar_volume_alto: bool = False, user_id: UUID | None = None) -> dict:
    """Assinatura existente + user_id opcional, repassado a AuditService.log_execution()."""


# mcp_transport/tools.py (modificado)
async def list_tools(current_user: AuthenticatedUser) -> list[Tool]: ...

async def call_tool(name: str, arguments: dict, current_user: AuthenticatedUser) -> dict: ...
```

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

Scenario: Emissão de token via script administrativo
  Given Um usuário cadastrado em `users`
  When O admin roda scripts/generate_access_token.py --user-id <uuid> --expires-days 90
  Then Um token é impresso 1 única vez
  And access_tokens.token_hash correspondente é criado, com expires_at = now() + 90 dias
  And O valor bruto do token não é persistido em nenhuma tabela

Scenario: Múltiplos tokens do mesmo usuário são independentes
  Given Usuário X com dois tokens (label "Claude Desktop" e "Gemini Desktop")
  When O token "Claude Desktop" é revogado
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


# tests/test_mcp_tools_auth.py
class TestMcpToolsAuth:
    @pytest.mark.asyncio
    async def test_list_tools_filters_by_user_permission(self): ...
    @pytest.mark.asyncio
    async def test_list_tools_empty_when_no_profile(self): ...
    @pytest.mark.asyncio
    async def test_call_tool_revalidates_permission(self): ...
    @pytest.mark.asyncio
    async def test_call_tool_denies_when_permission_revoked_after_list(self): ...
    @pytest.mark.asyncio
    async def test_call_tool_logs_user_id_in_execution_history(self): ...
```

### 6.2 Checklist de Testes
- [ ] Unitário: `generate_token`/`hash_token`
- [ ] Unitário: `AuthService.authenticate` (sucesso, token não encontrado, expirado, revogado, usuário bloqueado/inexistente)
- [ ] Unitário: `AuthService.is_analysis_allowed` (permitido, sem perfil, perfil inativo, análise inativa)
- [ ] Unitário: `list_tools()` filtra por permissão efetiva
- [ ] Unitário: `call_tool()` revalida (nega mesmo após aparecer em `list_tools()`)
- [ ] Unitário: `execution_history.user_id` gravado corretamente
- [ ] Integração: fluxo completo com token real gerado por `scripts/generate_access_token.py`
- [ ] Manual: testar via pelo menos 1 cliente MCP real com header `Authorization` configurado
- [ ] Manual: bloquear um usuário com sessão de cliente MCP já aberta e confirmar recusa imediata na próxima chamada

## 7. Mudanças na Configuração

**Variáveis de Environment (.env):**
```
ACCESS_TOKEN_EXPIRATION_DAYS=90  # validade padrão de novos tokens (scripts/generate_access_token.py)
```

**Dependências:** nenhuma nova — `secrets`/`hashlib` são da stdlib do Python.

## 8. Documentação

### 8.1 Como a feature aparece no MCP
Não aparece como uma tool nova: é uma camada de autenticação em frente a `list_tools()`/`call_tool()`. O efeito visível para o usuário é que a lista de tools passa a variar por token/usuário.

### 8.2 Como o usuário usa essa feature
1. Admin cadastra o usuário em `users` (SQL direto, como já é feito para `analyses`).
2. Admin vincula o usuário a 1+ `profiles` via `user_profiles`, e cada perfil às `analyses` liberadas via `profile_analyses`.
3. Admin gera o token: `python scripts/generate_access_token.py --user-id <uuid> --label "<cliente>" --expires-days 90`.
4. Usuário cola o token na configuração do cliente MCP (`Authorization: Bearer <token>`).
5. Quando o token expirar, o admin reemite (passo 3) e o usuário atualiza a config do cliente.

### 8.3 Como outros desenvolvedores estenderão isso
Um novo requisito de negócio (ex.: rate limiting por usuário — FB3) consome o mesmo `AuthenticatedUser` já resolvido em `list_tools()`/`call_tool()`, sem precisar reimplementar a autenticação. RBAC mais granular (ex.: permissão de leitura vs. escrita por analysis) estenderia `profile_analyses` com uma coluna de nível de acesso, sem mudar o modelo de token.

## 9. Checklist de Implementação

**Código:**
- [ ] `security/token_auth.py`
- [ ] `schemas/auth.py`
- [ ] `repositories/user_repo.py`, `profile_repo.py`, `access_token_repo.py`
- [ ] `services/auth_service.py`
- [ ] `services/analysis_service.py` — `get_allowed_analyses()`, `execute(..., user_id=)`
- [ ] `services/audit_service.py` / `repositories/execution_repo.py` — `user_id`
- [ ] `mcp_transport/tools.py` — `list_tools()`/`call_tool()` exigem `AuthenticatedUser`
- [ ] `scripts/generate_access_token.py`
- [ ] `database/models.py` + migration Alembic (tabelas F12 + `execution_history.user_id`)
- [ ] `config.py` — `ACCESS_TOKEN_EXPIRATION_DAYS`
- [ ] Testes (§6) passing
- [ ] Docstrings

**QA:**
- [ ] Code review aprovado
- [ ] Validação manual com cliente MCP real (§6.2)
- [ ] PR merge aprovado

---

## 10. Observações e Pendências (fora do escopo do F12)

| # | Observação | Situação |
|---|---|---|
| 1 | Sem CRUD/endpoint administrativo para `users`/`profiles`/vínculos — segue o padrão já usado para `analyses`/`data_sources` (INSERT direto) | Aceito em V1.0, consistente com o resto da plataforma |
| 2 | Sem tool MCP de auto-renovação de token — renovação é sempre manual (reemissão do script) | Decisão confirmada nesta sessão; pode virar backlog se o atrito for alto na prática |
| 3 | Forma exata de threading do `AuthenticatedUser` do header HTTP até dentro de `list_tools()`/`call_tool()` (middleware + contextvar, ou mecanismo do SDK `mcp`) | A confirmar na implementação — ver nota técnica em §4.2 |
| 4 | Identificação de qual cliente MCP/software está chamando (FB1) continua fora de escopo — `label` do token é só uma anotação administrativa, não uma identificação automática | Fora de escopo, ver FEATURES_ROADMAP.md §9 |
| 5 | Sem rate limiting/quota por usuário (FB3) | Fora de escopo, backlog futuro |
| 6 | `execution_history.user_id` fica `NULL` para todas as linhas gravadas antes do F12 | Aceito — sem backfill retroativo |

---

**Documento de Especificação F12 — Autenticação e Controle de Acesso via Perfis.**
**Sprint 3 — Production-Ready (aguardando implementação).**
