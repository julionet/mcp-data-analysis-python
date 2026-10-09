# F16 API Documentation (MCP + Multi-Cliente)

## Feature Spec

**ID:** F16
**Nome:** API Documentation — Swagger/OpenAPI (`/auth`, `/me`, `/admin`, `/health`) + Markdown (`/mcp`)
**Prioridade:** 🟡 Média
**Esforço Estimado:** 1d (8h)
**Status:** 🟩 Done (2026-10-08) — implementada; validação manual pendente (§6.2)

---

## 1. Visão
Documentar a API em duas frentes: **OpenAPI/Swagger** gerado pelo FastAPI para as rotas HTTP comuns (`/auth/*`, `/me`, `/admin/*`, `/health`), com o botão **Authorize** (Bearer) para executar os endpoints direto do navegador, e **Markdown** para o `/mcp`, cujo protocolo (Streamable HTTP/JSON-RPC) o OpenAPI não descreve. O Swagger só existe em **ambiente local**. Um arquivo `docs/openapi.json` versionado serve de contrato para o futuro frontend de gestão (F23–F25).

## 2. Objetivo
Quem for consumir a API (frontend, outro desenvolvedor, usuário de cliente MCP) deve conseguir: emitir um token, autorizar o Swagger e chamar qualquer endpoint sem ler o código; e entender o contrato do `/mcp` (tools, resultado, `error_code`/`retryable`) por um único documento.

**Métrica de Sucesso:**
- ✅ Com `DOCS_ENABLED=true`, `/docs`, `/redoc` e `/openapi.json` respondem 200; com `false` (ou ausente), 404
- ✅ No `/docs`: `POST /auth/token` → copiar o `token` → **Authorize** → `GET /me` e `GET /admin/users` respondem 200 (admin) sem montar header à mão
- ✅ Toda operação de `/admin/*` e `/me` aparece com cadeado; `/auth/*` e `/health` sem cadeado
- ✅ Toda operação tem `summary`, `description` e as respostas de erro reais (status + slug) documentadas
- ✅ `docs/openapi.json` gerado por script, válido (OpenAPI 3.1) e **coberto por teste de sincronia** com o código
- ✅ Contrato do `/mcp` documentado em Markdown, conferido contra o código
- ✅ Nenhuma mudança de comportamento das rotas (status, corpo, headers) — só metadados

## 3. Contexto
**Depende de:** F5 (MCP Tools), F12 (auth), F14 (contrato de erro), F23–F25 (API admin) — todas ✅
**É dependência de:** F21 (User Documentation — setup por cliente MCP)

**Estado atual medido (2026-10-08, `app.openapi()` do código atual, salvo como baseline em `docs/openapi.json`):**
- 44 operações em 31 paths; `info` = `{"title": "FastAPI", "version": "0.1.0"}` (padrão, nunca configurado)
- **Sem `securitySchemes`**: `get_current_user` lê o header cru de `request.scope` (`security/admin_auth.py`), então o Swagger não sabe que existe autenticação e **não mostra o botão Authorize**
- `FastAPI(lifespan=lifespan)` sem argumentos: `/docs`, `/redoc` e `/openapi.json` estão **ativos incondicionalmente**, inclusive no compose remote
- Nenhuma rota tem `summary`/`description`/`responses`/exemplos; todas as rotas `/admin/*` usam a tag única `admin`
- O `/mcp` (`add_route` + `mount`) **não aparece** no OpenAPI; `/health` aparece
- Erros de validação de corpo/query saem no formato padrão do FastAPI (`422 {"detail":[...]}`), diferente do slug `{"error","message"}` do restante (decisão: **só documentar**, ver §10)

## 4. Descrição Técnica

### 4.1 Componentes Afetados
```
├─ src/config.py                    (modificado: docs_enabled)
├─ src/main.py                      (modificado: docs_url/redoc_url/openapi_url condicionais; info; tags; description)
├─ src/security/admin_auth.py       (modificado: HTTPBearer como dependência → securityScheme)
├─ src/schemas/admin.py             (modificado: modelo ErrorResponse {error,message} p/ documentar `responses`)
├─ src/routes/*.py                  (modificado: tags, summary, description, responses, exemplos — SÓ metadados)
├─ src/schemas/*.py                 (modificado: Field(description=..., examples=...) nos modelos)
├─ scripts/export_openapi.py        (novo: gera docs/openapi.json sem banco)
├─ docs/openapi.json                (novo: gerado; baseline já criado, será regenerado)
├─ docs/MCP.md                      (novo: contrato do /mcp)
├─ tests/test_openapi_docs.py       (novo)
├─ .env.example                     (modificado: DOCS_ENABLED)
├─ docker-compose.local.yml         (modificado: DOCS_ENABLED=true no app)
├─ scripts/build-dist.ps1 / .sh     (verificar: o .env.example do dist é gerado ali — ver aviso no README §5)
└─ README.md                        (modificado: seção curta "Swagger (só local)")
```
`docker-compose.remote.yml` e `docker-compose.dist.yml` **não** definem `DOCS_ENABLED` → Swagger desligado (padrão seguro).

### 4.2 Swagger só em ambiente local (`DOCS_ENABLED`)
`TLS_ENABLED` não serve de critério (o compose remote também a define `false`). Nova variável:

```python
# config.py
docs_enabled: bool = False   # True só em ambiente local: expõe /docs, /redoc e /openapi.json

# main.py
app = FastAPI(
    lifespan=lifespan,
    title=..., version=..., description=..., openapi_tags=...,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
```
- `app.openapi()` continua funcionando com `openapi_url=None` (o script de exportação não depende da flag).
- Desligado = as 3 URLs devolvem 404 (não 401/403: a existência não é revelada).
- Registrar em log no startup quando ligado (`logger.warning("Swagger habilitado (DOCS_ENABLED=true) — use só em ambiente local")`).
- **Fora de escopo:** proteger o `/docs` por autenticação (o botão Authorize autentica as *chamadas*, não o acesso à página — mesmo em local isso basta).

### 4.3 Botão Authorize (Bearer)
Em `security/admin_auth.py`, declarar o esquema do FastAPI e consumi-lo em `get_current_user`:

```python
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(
    scheme_name="BearerToken",
    description="Token opaco emitido por POST /auth/token. Cole só o token (o Swagger acrescenta 'Bearer ').",
    auto_error=False,   # essencial: sem token a dependência NÃO levanta o 403 do FastAPI;
)                       # quem responde é o get_current_user, com o 401 {"error":"unauthorized"} atual.

async def get_current_user(
    request: Request,
    _credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),  # só registra o esquema no OpenAPI
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthenticatedUser:
    ...  # corpo inalterado: continua usando _extract_bearer(request.scope)
```
- `auto_error=False` preserva o contrato de erro (401 `unauthorized` + `WWW-Authenticate: Bearer`). **Teste obrigatório** garante que a resposta sem token é idêntica à atual.
- `require_admin` depende de `get_current_user` → herda o cadeado; `/me/*` idem. `/auth/*` e `/health` não dependem → sem cadeado.
- O `AuthMiddleware` do `/mcp` não muda (está fora do OpenAPI).
- Fluxo no Swagger: `POST /auth/token` (Try it out, e-mail+senha) → copiar `token` → **Authorize** → colar → executar qualquer rota.

### 4.4 Metadados da API (OpenAPI `info` e tags)
| Campo | Valor (confirmado, §10) |
|---|---|
| `title` | `Análise de Dados Genérica com MCP — API HTTP` (confirmado) |
| `version` | `1.0.0` (projeto é "V1.0"; hoje `0.1.0` por padrão) |
| `description` | Resumo + aviso de que o `/mcp` não está neste documento (link `docs/MCP.md`) + como autenticar + formato de erro |
| `tags` | `auth`, `me`, `health` e, no lugar da tag única `admin`: `admin-users`, `admin-profiles`, `admin-data-sources`, `admin-analyses`, `admin-executions` — cada uma com descrição |

Sem `contact`/`license`/`servers`: não há dado definido no projeto (não inventar).

### 4.5 Documentação por operação
Para cada uma das 44 operações:
- `summary` (curto) e `description` (regras de negócio já decididas nas specs: ex. exclusão híbrida 409, PATCH mescla `connection_config`, senha Fernet nunca devolvida, `validate` só estático, `cache/invalidate` = `updated_at = NOW()`, revogação de todos os tokens em `PUT /me/password`)
- `responses=` com **todos** os status reais e o modelo `ErrorResponse`:
  - `/admin/*` e `/me`: 401 `unauthorized`, 403 `forbidden` (só `/admin/*`), 422 padrão FastAPI (`HTTPValidationError`) e os 400/404/409/422 de domínio de cada rota
  - `/auth/*`: 401 `invalid_credentials`, 400 `invalid_expire_days`, 404 `token_not_found`
- Descrição de campos (`Field(description=...)`) e `examples` nos corpos de entrada/saída; exemplos usam dados fictícios evidentes (`maria@exemplo.com`), nunca valores reais
- Os **slugs e códigos HTTP vêm das classes `AdminError`** (`schemas/admin.py`) — não digitados à mão sem conferência (ver teste 6.1 item 5)

Modelo novo:
```python
class ErrorResponse(BaseModel):
    error: str = Field(description="Slug estável do erro, ex.: 'user_not_found'")
    message: str = Field(description="Mensagem legível em português")
```
Só descreve o corpo no OpenAPI; as rotas continuam devolvendo `JSONResponse` via `AdminRoute` (sem `response_model` de erro).

### 4.6 Arquivo OpenAPI (`docs/openapi.json`)
`scripts/export_openapi.py`:
- Define variáveis dummy com `os.environ.setdefault` (`POSTGRES_CONFIG_*`, `FERNET_KEY` gerada) para `Settings()` não falhar; **não conecta em banco** (a conexão é feita só no `lifespan`)
- `json.dump(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True)` + `\n` final — saída determinística (diff estável)
- Uso: `.venv/bin/python scripts/export_openapi.py` (`--check` sai com código 1 se o arquivo versionado estiver desatualizado — usado pelo teste)
- **Baseline atual** já gerado em `docs/openapi.json` (código inalterado: sem Authorize, `title` "FastAPI"); será **regenerado** ao implementar

### 4.7 Documentação do `/mcp` (`docs/MCP.md`)
O OpenAPI não cobre. Conteúdo (cada afirmação conferida contra o código/ARQUITETURA no momento de escrever):
1. Endpoint único `/mcp`, Streamable HTTP **stateless**, TLS obrigatório fora do local; `Authorization: Bearer <token>` em toda chamada; 401 do `AuthMiddleware`
2. Como obter o token (`POST /auth/token`) — link para o Swagger/README
3. `list_tools`: uma tool por análise ativa liberada ao usuário, nome `execute_<analysis.name>`, `inputSchema` do JSON Schema de `analyses.parameters` + `confirmar_volume_alto` (booleano)
4. `call_tool`: formatos de retorno `success` (`data`, `cached`, `aviso` opcional), `volume_exceeded` (`estimativa`, `limite`, `mensagem`) e `error` — tabela dos 7 `error_code`/`retryable` (fonte: ARQUITETURA.md §3.4.1; **não duplicar divergindo** — referenciar e conferir)
5. Regras: acesso negado = `ANALYSIS_NOT_FOUND`; erro nunca vaza exceção; retry só de falha rápida de conexão; como refinar e reenviar após `volume_exceeded`/`QUERY_TIMEOUT`
6. **Configuração por cliente:** Claude Code (`claude mcp add --transport http ... --header "Authorization: Bearer $TOKEN"`) — referenciar o README §6 em vez de copiar. Demais clientes: escopo da F21 (§10)

## 5. Critérios de Aceitação
```gherkin
Feature: Documentação da API

Scenario: Swagger disponível em ambiente local
  Given DOCS_ENABLED=true
  When GET /docs, /redoc e /openapi.json
  Then todos respondem 200

Scenario: Swagger indisponível fora do local
  Given DOCS_ENABLED ausente ou false
  When GET /docs, /redoc e /openapi.json
  Then todos respondem 404

Scenario: Autorizar e executar pelo Swagger
  Given o /docs aberto e um administrador cadastrado
  When executo POST /auth/token, copio o token e clico em Authorize
  And executo GET /admin/users
  Then recebo 200 com a lista, sem preencher header manualmente

Scenario: Rota protegida sem token continua com o erro atual
  Given a dependência bearer_scheme com auto_error=False
  When GET /admin/users sem Authorization
  Then 401 {"error":"unauthorized","message":"Token de acesso inválido ou ausente."} com WWW-Authenticate: Bearer

Scenario: Cadeado só onde há autenticação
  Given o openapi.json
  Then toda operação de /admin/* e /me tem security [BearerToken]
  And POST /auth/token, POST /auth/revoke e GET /health não têm

Scenario: Arquivo versionado em sincronia
  Given docs/openapi.json commitado
  When o código das rotas muda sem regenerar o arquivo
  Then o teste de sincronia falha indicando o comando de regeneração
```

## 6. Testes

### 6.1 Testes Unitários (`tests/test_openapi_docs.py`, sem banco)
1. `DOCS_ENABLED` false/ausente → 3 URLs 404; true → 200 (app montado com a flag via fixture que recarrega a criação do app, sem tocar no `app` global dos demais testes)
2. `securitySchemes.BearerToken` existe (`type: http`, `scheme: bearer`); toda operação `/admin/*` e `/me*` tem `security`; `/auth/*` e `/health` não
3. Sem token → resposta idêntica à atual (401, slug, `WWW-Authenticate`) em uma rota `/admin/*` e em `/me` — prova do `auto_error=False`
4. Toda operação tem `summary`, `description` e `tags` não vazios; `info.title/version` configurados; nenhuma tag fora das declaradas em `openapi_tags`
5. Para cada subclasse de `AdminError`: o `(status_code, error)` aparece em algum `responses` do OpenAPI (garante que um erro novo não fique sem documentação)
6. Rotas protegidas declaram 401 (e `/admin/*` também 403) com `ErrorResponse`
7. `docs/openapi.json` == `app.openapi()` serializado pelo script (`--check`)
8. `docs/openapi.json` é JSON válido, `openapi` 3.1.x, 44+ operações; nenhum campo de resposta chamado `password`, `password_hash`, `token_hash`, `connection_config.password`
9. `/mcp` não consta no OpenAPI (documentado em Markdown) — evita doc enganosa

### 6.2 Checklist de Testes
- [x] Teste unitário: flag do Swagger (liga/desliga)
- [x] Teste unitário: securityScheme e cadeados
- [x] Teste unitário: erro 401 inalterado (regressão)
- [x] Teste unitário: cobertura de documentação (summary/description/erros)
- [x] Teste unitário: sincronia do `docs/openapi.json`
- [x] Suíte completa (`pytest tests -m "not integration" --cov`) continua ≥ 90% e sem regressão (849 testes antes; 852 depois, 99,89%)
- [ ] **Manual:** compose local → `/docs` → emitir token → Authorize → executar 1 rota de cada grupo (`/me`, users, profiles, data-sources, analyses, executions)
- [ ] **Manual:** compose remote → `/docs` retorna 404 (via nginx)
- [ ] **Manual:** ler `docs/MCP.md` e executar o `claude mcp add` descrito, listando a tool

## 7. Mudanças na Configuração
```
# .env.example (e docker-compose.local.yml, serviço app)
DOCS_ENABLED=true    # Swagger (/docs, /redoc, /openapi.json) — só ambiente local; padrão false
```
- Sem DDL. Sem dependência nova (`json` da stdlib; **não usar** PyYAML — formato escolhido: JSON)
- Pacote `dist` (`build-dist.ps1`/`.sh` geram o `.env.example` próprio): **sem** `DOCS_ENABLED` (Swagger desligado) — conferir se o aviso do README §5 pede replicar a variável

## 8. Documentação
### 8.1 Como a feature aparece
Em ambiente local: `http://localhost:3000/docs` (Swagger UI, botão **Authorize**) e `/redoc`. Fora dele: nada exposto.
### 8.2 Como o usuário usa
1. Subir o compose local (`DOCS_ENABLED=true`) → abrir `/docs`
2. `POST /auth/token` → copiar `token` → **Authorize** → colar
3. Executar qualquer rota; sessão do Swagger é por aba (recarregar pede Authorize de novo, comportamento padrão)
4. Frontend/terceiros: usar `docs/openapi.json` (geradores de cliente, Postman, etc.)
### 8.3 Como outros desenvolvedores estenderão
Rota nova ⇒ `summary`/`description`/`responses`/`tags` obrigatórios (o teste 6.1-4/5 falha sem eles) ⇒ rodar `scripts/export_openapi.py` e commitar `docs/openapi.json` (o teste 6.1-7 falha se esquecer). Novo `AdminError` ⇒ documentar o status na(s) rota(s) que o levantam.

## 9. Checklist de Implementação
**Código:**
- [x] `DOCS_ENABLED` em `config.py` + `main.py` + `.env.example` + compose local (+ aviso em log)
- [x] `HTTPBearer(auto_error=False)` em `get_current_user`
- [x] `ErrorResponse` + `info`/`tags` + metadados de todas as 44 operações
- [x] `scripts/export_openapi.py` (+ `--check`) e `docs/openapi.json` regenerado
- [x] `docs/MCP.md` conferido contra `tools.py`/ARQUITETURA §3.4.1
- [x] README: seção "Swagger (só local)" e link para `docs/`
- [x] Testes passando; cobertura ≥ 90%
- [x] Atualizar CLAUDE.md, FEATURES_ROADMAP.md e ARQUITETURA.md (§2.4 endpoints) ao concluir

**QA:**
- [ ] Validações manuais da §6.2 (itens de §6.2 não confirmados individualmente)
- [x] Revisão de que nenhuma rota mudou de comportamento (diff só de metadados + 1 dependência)

## 10. Decisões tomadas e pendências

**Decididas (2026-10-08):**
| # | Decisão |
|---|---|
| 1 | Swagger só em ambiente local, controlado por nova variável **`DOCS_ENABLED`** (padrão `false`) |
| 2 | Arquivo **`docs/openapi.json`** (JSON), gerado por script, com teste de sincronia |
| 3 | Erro 422 de validação de corpo: **só documentar** o formato padrão do FastAPI (`{"detail":[...]}`); padronizar para `{"error","message"}` fica como decisão futura (muda contrato) |
| 4 | Clientes MCP: **só Claude Code** (README §6); demais clientes ficam para a F21 |

**Pendências resolvidas (2026-10-08):**
| # | Decisão |
|---|---|
| P1 | `info.title` = "Análise de Dados Genérica com MCP — API HTTP"; `info.version` = `1.0.0` |
| P2 | `servers`, `contact` e `license` **ficam de fora** |
| P3 | Outros clientes MCP (Claude Desktop/`mcp-remote`, Gemini, OpenAI) ficam para a **F21**; `docs/MCP.md` documenta só o Claude Code |
| P4 | Descrições do Swagger em **português** |
| P5 | `/mcp` **fora** do `openapi.json` (só Markdown) |

**Sem pendências abertas.**

**Riscos:** (a) `HTTPBearer` mal configurado trocaria o 401 do projeto pelo 403 do FastAPI → coberto pelo teste 6.1-3; (b) 44 operações × metadados é trabalho volumoso mas mecânico — a descrição de cada regra de negócio deve vir das specs F12/F23/F24/F25, sem criar comportamento novo; (c) `docs/openapi.json` fica desatualizado se esquecerem de regenerar → teste de sincronia.

## 11. Implementação (2026-10-08)

**Resultado:** 852 testes unitários ✅ (`pytest tests -m "not integration" --cov`, 20 de integração não rodados — exigem o Postgres do compose), cobertura **99,89%** (única linha descoberta de `main.py`: o `logger.warning` de "Swagger habilitado", que só roda com a flag ligada no processo de teste). `docs/openapi.json` em sincronia (`scripts/export_openapi.py --check`). F16 confirmada como implementada pelo usuário; as validações manuais da §6.2 (Authorize no `/docs` do compose local, `/docs` 404 no remote via nginx, `claude mcp add` conforme `docs/MCP.md`) **não foram registradas uma a uma**.

**Arquivos novos:** `src/routes/openapi_docs.py` (tags, `OPENAPI_TAGS`, `slug_response`, `admin_responses`, `me_responses`), `scripts/export_openapi.py`, `docs/openapi.json`, `docs/MCP.md`, `tests/test_openapi_docs.py` (23 testes). **Modificados:** `src/config.py` (`docs_enabled`), `src/main.py` (`docs_urls()`, `title`/`version`/`description`/`openapi_tags`, tag e descrição do `/health`), `src/security/admin_auth.py` (`bearer_scheme`), `src/schemas/admin.py` e `src/schemas/auth.py` (`Field(description=...)` e `example` nos corpos de entrada; `ErrorResponse`, `ValidationErrorItem`, `ValidationErrorBody`), todos os `src/routes/*.py` (tags, `summary`, `description`, `responses`), `.env.example`, `docker-compose.local.yml`, `README.md` (seção "Documentação da API (Swagger, só local)").

**Desvios em relação ao desenho:**
- `docs_urls(enabled)` em `main.py` (não previsto): isola a decisão das 3 URLs para ser testável sem recarregar o app global.
- O 422 das rotas com erro de domínio 422 (`invalid_reference`, `invalid_connection_config`, `invalid_analysis_definition`, `invalid_period`, `invalid_parameters_filter`, `unsupported_data_source_type`) é documentado como `ErrorResponse | ValidationErrorBody` (`anyOf`): o FastAPI só acrescenta o 422 padrão quando a rota não declara nenhum 422, então a união mantém os dois formatos visíveis. As rotas sem 422 de domínio mantêm o `HTTPValidationError` automático.
- Os modelos `ValidationErrorBody`/`ValidationErrorItem` são próprios (`schemas/admin.py`) em vez de reutilizar o `HTTPValidationError` do FastAPI, para não colidir com o schema que o framework registra sozinho.
- Os metadados foram aplicados por script de edição das decorações `@router.<método>(...)`; nenhuma lógica de rota mudou. Cada afirmação das descrições (revogação de tokens ao redefinir a senha, `q` por nome/descrição, cascata do perfil, mescla do PATCH de `connection_config`) foi conferida no serviço/repositório correspondente.
- Os exemplos de corpo (`maria@exemplo.com`, `Exemplo@123`) aparecem pré-preenchidos no "Try it out" do Swagger. Observado em uso: trocar só um dos campos de `POST /auth/token` mantém o outro valor de exemplo e resulta em `invalid_credentials`.
- O teste `test_every_admin_error_is_documented` percorre as subclasses de `AdminError` definidas em `schemas/admin.py` (25 classes) e exige o par (status, slug) em algum `responses` — o critério "erro novo sem documentação quebra o teste" da §8.3.

**Pendências / fora de escopo mantidos:** outros clientes MCP (Claude Desktop/`mcp-remote`, Gemini, OpenAI) na F21; padronização do 422 de validação para `{"error","message"}` (decisão futura, muda contrato); `/mcp` fora do OpenAPI; proteção do `/docs` por autenticação (a flag é o controle).

**Como regenerar o contrato:** `.venv/bin/python scripts/export_openapi.py` (grava) e `--check` (usado pelo teste de sincronia).
