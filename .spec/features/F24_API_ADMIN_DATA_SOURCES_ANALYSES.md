# F24 — API Administrativa: Data Sources + Analyses

## Feature Spec

**ID:** F24
**Nome:** API Administrativa — data sources (`/admin/data-sources`) e analyses (`/admin/analyses`)
**Prioridade:** 🟠 Alta
**Esforço Estimado:** 3d
**Status:** 🟩 Done (2026-10-08) — validação manual pendente (§6.3)

> **Origem dos requisitos:** NEGOCIO.md v1.12 (RF6, UC4), ARQUITETURA.md v1.26 (§2.4 "F24", §3.2 chave do cache, §2.3 parâmetros, ADR-008), FEATURES_ROADMAP.md v1.22, DATABASE_SCHEMA.md (§2.1–§2.3, §3, §4, §8) e `features/F23_API_ADMIN_USUARIOS_PERFIS.md` (convenções comuns, `require_admin`, `transaction()`, paginação, formato de erro). Esta spec cobre só a **F24**; o histórico de execuções é a F25.

---

## 1. Visão

Hoje data sources e analyses (com seu step e vínculos a perfis) só entram no Config DB por INSERT manual, com a senha do data source cifrada à mão por script. A F24 entrega, na API `/admin/*` da F23, a gestão completa de **data sources** (com senha Fernet que nunca sai da API, teste de conexão e tipos suportados) e de **analyses** (análise + step + perfis numa única transação, validação da definição e invalidação do cache), para um futuro frontend de gestão.

## 2. Objetivo

Permitir que um administrador cadastre, altere, desative, exclua e teste data sources, e cadastre/edite/valide analyses prontas para execução pelo `/mcp`, sem acesso ao banco — com a garantia de que toda alteração é refletida na execução seguinte (cache e pool de conexões coerentes).

**Métrica de Sucesso:**
- ✅ Todas as rotas novas exigem `require_admin` (a varredura de rotas `/admin/*` da F23 cobre as novas automaticamente: 401 sem token, 403 sem `is_admin`)
- ✅ `connection_config.password` é cifrada ao gravar e **nunca** aparece em resposta, log nem mensagem de erro
- ✅ Análise criada pela API executa pelo `/mcp` sem nenhum passo manual (tem step, parâmetros válidos, SQL aceito pelo engine)
- ✅ Editar análise ou step atualiza `analyses.updated_at`: a execução seguinte não serve o resultado antigo do cache
- ✅ Editar/desativar um data source derruba o pool em `AnalysisService._adapters`: a execução seguinte usa a configuração nova (ou falha com `DATA_SOURCE_UNAVAILABLE` se desativado)
- ✅ Criação de análise é atômica (análise + step + perfis; rollback testado)
- ✅ Exclusão física só sem dependentes (409 com análises/histórico)
- ✅ Os 571 testes atuais continuam passando; `/mcp`, `/auth/*` e as rotas da F23 inalterados

## 3. Contexto

**Depende de:** F23 (`require_admin`, `AdminRoute`, `AdminError`, `Page`, `transaction()`, `sql_helpers`, `routes/dependencies.py`, evento `admin_action`), F4 (engine: lê só o primeiro step, `validate_select_only`, `validate_schema`), F7 (chave do cache inclui `updated_at`), F12 (`profile_analyses`)
**É dependência de:** F25 (`GET /admin/analyses/{id}/executions` reutiliza o router de analyses), F16 (documentação), F17 (cobertura)

**Estado do código (verificado antes de escrever):**
- `DataSourceRepository` só tem `get_by_id`; `AnalysisRepository` só leitura — `get_by_id` e `get_all` filtram `is_active = true`; `get_by_name` e `get_steps` não. Não existe create/update/delete/list em nenhum dos dois.
- `analysis_service` é um singleton criado em `mcp_transport/tools.py` (junto com `_cache_service`/`_data_source_repo`); `main.py` já o importa. As rotas admin da F23 **não** importam `mcp_transport.tools` (`routes/dependencies.py` monta tudo sobre `config_db_adapter`). A F24 precisa do singleton para invalidar o pool — ver §4.3.
- `AnalysisService._get_adapter` guarda o adapter por `data_source_id` em `_adapters` (com `_adapters_lock`) e nunca o invalida; `aclose()` só roda no shutdown.
- `CacheBackend` só tem `get`/`set`/`delete(key)`; a chave (`CacheService.build_key`) é `analysis:<id>:<sha256(updated_at|params)>` — não há como apagar "todas as chaves de uma análise".
- O engine executa `steps[0]`, chama `validate_select_only(sql)` e `adapter.translate_params(sql, step.definition["params"])`, depois `values[name] for name in param_names`. Consequências verificadas: todo nome em `params` precisa existir em `analyses.parameters`; um `:placeholder` do SQL ausente de `params` **não** é traduzido (erro no banco); um nome em `params` ausente do SQL gera mais valores que placeholders (erro no PostgreSQL).
- O asyncpg não tem codec JSONB (valores chegam como `str` e precisam ser enviados como `$n::jsonb` com `json.dumps`).
- `adapter.test_connection()` devolve `bool` e **engole** a exceção; `connect()` levanta a exceção real. O adapter PostgreSQL lê `pool_min_size`/`pool_max_size` do `connection_config` (F15).
- `encrypt_password` já existe em `security/crypto.py`; `decrypt_password` só é chamada pelo `AnalysisService`.
- Não há `--workers` em `run_https.py` nem nos compose (um processo); o cache e os pools são em memória do processo.

---

## 4. Descrição Técnica

### 4.1 Componentes Afetados

```
Componentes criados/modificados:
├─ schemas/data_source_types.py     (novo) tipos suportados, campos obrigatórios/opcionais por tipo,
│                                    validate_connection_config()
├─ schemas/sql_validation.py        (modificado) + extract_placeholders(sql)
├─ schemas/admin.py                 (modificado) modelos de request/response e exceções da F24
├─ repositories/data_source_repo.py (modificado) list/count/create/update/delete, contagem de analyses,
│                                    get_by_name; db opcional
├─ repositories/analysis_repo.py    (modificado) listagem admin (inclui inativas), count, get_any_by_id,
│                                    create/update/delete, upsert do step, profile_analyses, contagem de histórico
├─ services/data_source_admin_service.py (novo)
├─ services/analysis_admin_service.py    (novo)
├─ services/analysis_service.py     (modificado) + invalidate_data_source(id)
├─ routes/admin_data_sources.py     (novo) /admin/data-sources
├─ routes/admin_analyses.py         (novo) /admin/analyses
├─ routes/dependencies.py           (modificado) + get_data_source_admin_service(), get_analysis_admin_service()
├─ main.py                          (modificado) include_router dos dois routers
└─ (sem mudança) CORS já permite PUT/PATCH (F23); requirements.txt
```

### 4.2 Autorização e convenções

Idênticas à F23 (§4.2 e §4.3 daquela spec): cada router é criado com `route_class=AdminRoute` e `dependencies=[Depends(require_admin)]`; ator via `Depends(get_current_user)` onde a escrita precisa dele (`created_by`, log); paginação `limit` (padrão 50, máx. 200) / `offset`, resposta `{items,total,limit,offset}`; busca `?q=` por `ILIKE` com curingas escapados (`like_pattern`); erros `{"error","message"}`; log `admin_action actor_id=%s action=%s target_type=%s target_id=%s` em toda escrita bem-sucedida (**sem** senha, SQL, `connection_config` nem e-mail); 422 padrão do FastAPI para corpo/query inválidos; `updated_at = NOW()` em toda escrita; repositórios aceitam `db` opcional (adapter ou transação).

Ordenação das listagens: `ORDER BY name, id`.

### 4.3 Acesso ao `AnalysisService` (invalidação do pool)

A F23 decidiu não importar `mcp_transport.tools` em `routes/dependencies.py`. A F24 precisa de **um** ponto do singleton `analysis_service` (chamar `invalidate_data_source`). Desenho: `get_data_source_admin_service()` faz **import tardio** de `mcp_transport.tools.analysis_service` (como `get_auth_service` faz hoje) e o injeta no `DataSourceAdminService` como dependência `pool_invalidator` (qualquer objeto com `async invalidate_data_source(id)`); os testes de rota usam `dependency_overrides`/fake. O import tardio evita carregar o Config DB ao importar o módulo.

```python
# services/analysis_service.py
async def invalidate_data_source(self, data_source_id: UUID) -> None:
    """Remove e fecha o adapter cacheado do data source (se houver). A próxima execução
    recria o adapter com o connection_config atual. Idempotente."""
    async with self._adapters_lock:
        adapter = self._adapters.pop(data_source_id, None)
    if adapter is not None:
        await adapter.disconnect()      # fora do lock; erro de desconexão só é logado
```

Execuções em andamento que seguram o adapter antigo podem falhar (viram `QUERY_FAILED`/`DATA_SOURCE_UNAVAILABLE`, retryáveis conforme a F14); é aceito. A invalidação é **depois do commit** da alteração; se ela falhar, a alteração permanece e o erro é logado (a API ainda responde sucesso — o pool antigo some no próximo restart).

### 4.4 Data sources — `/admin/data-sources`

#### 4.4.1 Tipos e validação do `connection_config`

`schemas/data_source_types.py` (fonte única; espelha DATABASE_SCHEMA.md §4 e o `AdapterFactory`):

| `type` | Obrigatórias | Opcionais (padrão do adapter) |
|---|---|---|
| `postgresql` | `host`, `port`, `database`, `user`, `password` | `pool_min_size`, `pool_max_size` (F15; padrão = `PG_POOL_*`) |
| `mysql` | `host`, `database`, `user`, `password` | `port` (3306) |
| `sqlserver` | `host`, `database`, `user`, `password` | `port` (1433), `driver` (`ODBC Driver 18 for SQL Server`), `sslmode` (`prefer` \| `verify-full`; padrão `prefer`) |
| `oracle` | `host`, `user`, `password` e **`service_name` ou `sid`** (exatamente um) | `port` (1521) |

`validate_connection_config(type, config) -> None` (levanta `InvalidConnectionConfigError`, 422 `invalid_connection_config`, mensagem listando os campos):
- `type` ∈ tipos do `AdapterFactory` (senão 422 `unsupported_data_source_type` listando os aceitos);
- chaves obrigatórias presentes e strings não vazias (`password` incluída); `port` inteiro 1–65535; `pool_min_size`/`pool_max_size` inteiros ≥ 1 com `min ≤ max`; `sslmode` ∈ {`prefer`,`verify-full`}; Oracle com `service_name` xor `sid`;
- **chave desconhecida para o tipo → 422** (evita lixo no JSONB e erro de digitação silencioso, p. ex. `passwrd`).

`GET /admin/data-sources/types` devolve a mesma tabela para o frontend montar formulários: `[{type, required: [...], optional: [{name, default}], one_of: [["service_name","sid"]] | []}]`.

#### 4.4.2 Endpoints

| Método | Path | Corpo / Query | Sucesso | Erros |
|---|---|---|---|---|
| GET | `/admin/data-sources/types` | — | 200 lista de tipos (§4.4.1) | 401, 403 |
| GET | `/admin/data-sources` | `q`, `type`, `is_active`, `limit`, `offset` | 200 lista paginada de `DataSourceSummary` | 401, 403 |
| POST | `/admin/data-sources` | `{name, type, connection_config, is_active=true}` | 201 `DataSourceDetail` | 409 `data_source_name_already_exists`, 422 `invalid_connection_config` / `unsupported_data_source_type` |
| GET | `/admin/data-sources/{id}` | — | 200 `DataSourceDetail` | 404 `data_source_not_found` |
| PATCH | `/admin/data-sources/{id}` | `{name?, is_active?, connection_config?}` (ao menos um) | 200 `DataSourceDetail` | 404, 409 `data_source_name_already_exists`, 422 `invalid_connection_config` |
| DELETE | `/admin/data-sources/{id}` | — | 204 | 404, 409 `data_source_has_analyses` |
| POST | `/admin/data-sources/{id}/test-connection` | — | 200 `ConnectionTestResult` | 404 |
| POST | `/admin/data-sources/test-connection` | `{type, connection_config}` (senha em texto, **sem gravar**) | 200 `ConnectionTestResult` | 422 `invalid_connection_config` |

(`/types` e `/test-connection` são declaradas antes de `/{id}` e `id` é `UUID`, então não colidem.)

Modelos:
- `DataSourceSummary`: `id, name, type, is_active, analyses_count, created_by, created_at, updated_at`
- `DataSourceDetail`: `DataSourceSummary` + `connection_config` (**sem `password`**) + `has_password: bool` + `analyses: [{id, name, is_active}]`
- `ConnectionTestResult`: `{ok: bool, message: str, error_type: str | null, elapsed_ms: int}`

Regras:
- **Criar:** valida o `connection_config` (§4.4.1), cifra `password` com `encrypt_password` e grava; `created_by` = e-mail (`external_id`) do admin autenticado (como a F23, decisão 12). Não testa a conexão ao gravar (o teste é uma ação explícita) — um data source pode ser cadastrado antes de o banco estar no ar.
- **Alterar (PATCH):** só os campos enviados são gravados. `type` **não** é alterável (§11, P1). `connection_config` é **mesclado** com o salvo: chaves enviadas substituem, chaves omitidas permanecem, `null` numa chave **opcional** a remove (volta ao padrão), `null` numa obrigatória → 422. `password` só é recifrada se enviada; se omitida, o valor cifrado salvo é preservado sem ser decifrado. O resultado da mesclagem é revalidado por inteiro (§4.4.1) — para isso a validação trata `password` como presente quando há valor cifrado salvo.
- **Efeitos colaterais do PATCH**, depois do commit: se `connection_config` ou `is_active` mudou → `invalidate_data_source(id)` (§4.3) **e** `UPDATE analyses SET updated_at = NOW() WHERE data_source_id = $1` na mesma transação da alteração (§11, P2 — o cache não conhece o data source; sem isso, resultados do banco antigo seguem sendo servidos até o TTL, que chega a 7 dias). Mudar só o `name` não dispara nada disso.
- **Desativar** (`is_active=false`) não é bloqueado por ter análises: as execuções passam a falhar com `DATA_SOURCE_UNAVAILABLE` (comportamento já documentado em DATABASE_SCHEMA.md §2.1), que é exatamente o efeito pedido.
- **Excluir:** 409 `data_source_has_analyses` se existir qualquer análise (ativa ou inativa) apontando para ele — a mensagem orienta desativar (FK sem `ON DELETE`). `ForeignKeyViolationError` por corrida também vira 409. Depois do delete: `invalidate_data_source(id)`.
- **Testar conexão (salvo):** carrega o data source, decifra a senha, cria o adapter via `AdapterFactory` e executa `connect()` → `test_connection()` → `disconnect()` (sempre, em `finally`), tudo sob `asyncio.wait_for` de **10 s** (constante no serviço, sem variável de ambiente nova). **Sem retry** (o retry da F14 é do caminho de execução). Funciona também com data source inativo (permite testar antes de ativar). Usa um adapter **temporário**, nunca o pool de `AnalysisService`.
- **Testar conexão (prévio):** mesmo fluxo, com `type` + `connection_config` do corpo (validados como no cadastro; a senha vem em texto e não é cifrada nem gravada).
- **Resposta do teste:** sempre 200 (a falha é parte do resultado). `ok=false` traz `message` em português por categoria — *tempo esgotado* (`is_timeout_error` ou `TimeoutError` do `wait_for`), *falha de conexão* (`is_transient_error`), *credenciais ou configuração recusadas/ erro ao consultar* (demais) — e `error_type` = nome da classe da exceção. **O texto da exceção do driver não é devolvido** (pode ecoar host/usuário/DSN); o detalhe completo vai para o log com a senha mascarada. `test_connection()` que devolve `False` (SELECT 1 falhou) → `ok=false`, mensagem de consulta.

### 4.5 Analyses — `/admin/analyses`

#### 4.5.1 Endpoints

| Método | Path | Corpo / Query | Sucesso | Erros |
|---|---|---|---|---|
| GET | `/admin/analyses` | `q`, `data_source_id`, `is_active`, `limit`, `offset` | 200 lista paginada de `AnalysisSummary` | 401, 403 |
| POST | `/admin/analyses` | `AnalysisCreate` (abaixo) | 201 `AnalysisDetail` | 409 `analysis_name_already_exists`, 422 `invalid_analysis_definition`, 422 `invalid_reference` |
| GET | `/admin/analyses/{id}` | — | 200 `AnalysisDetail` | 404 `analysis_not_found` |
| PATCH | `/admin/analyses/{id}` | `AnalysisUpdate` (ao menos um campo) | 200 `AnalysisDetail` | 404, 409 `analysis_name_already_exists`, 422 `invalid_analysis_definition` / `invalid_reference` |
| DELETE | `/admin/analyses/{id}` | — | 204 | 404, 409 `analysis_has_history` |
| PUT | `/admin/analyses/{id}/profiles` | `{profile_ids}` (substitui o conjunto) | 200 `AnalysisDetail` | 404, 422 `invalid_reference` |
| POST | `/admin/analyses/{id}/validate` | — | 200 `ValidationReport` | 404 |
| POST | `/admin/analyses/{id}/cache/invalidate` | — | 200 `{"invalidated": true, "updated_at": "..."}` | 404 |

Modelos de entrada:
```python
class StepInput(BaseModel):                    # criação: ambos; PATCH: ao menos um
    sql: str                                   # min 1, sem limite além do TEXT do JSONB
    params: list[str] = []                     # ordenada; define a ordem dos placeholders

class AnalysisCreate(BaseModel):
    name: str                                  # 1–255
    description: str | None = None
    data_source_id: UUID
    cache_frequency: str = "daily"             # hourly | daily | weekly | none
    parameters: dict[str, Any] = {}            # formato de DATABASE_SCHEMA.md §3
    is_active: bool = True
    step: StepInput
    profile_ids: list[UUID] = []

class AnalysisUpdate(_AtLeastOneField):        # todos opcionais; `parameters` SUBSTITUI o objeto inteiro
    name: str | None; description: str | None; data_source_id: UUID | None
    cache_frequency: str | None; parameters: dict[str, Any] | None
    is_active: bool | None; step: StepInput | None   # no PATCH, sql e params são opcionais dentro de step
```
Modelos de saída:
- `AnalysisSummary`: `id, name, description, data_source_id, data_source_name, cache_frequency, is_active, profiles_count, created_by, created_at, updated_at`
- `AnalysisDetail`: `AnalysisSummary` + `parameters` + `step: {id, step_order, step_type, sql, params}` (o primeiro step; `null` se a análise legada não tiver) + `profiles: [{id, name, is_active}]`
- `ValidationReport`: `{valid: bool, errors: [{code, field, message}], warnings: [{code, field, message}]}`

#### 4.5.2 Regras

- **Listagem administrativa inclui análises inativas** (diferente do `/mcp`). `AnalysisRepository.get_by_id/get_all` **não mudam** (o engine e o `/mcp` dependem do filtro); a API usa métodos novos (`admin_list`, `admin_count`, `get_any_by_id`).
- **Validação de definição (criar e alterar)** — mesma função usada por `/validate` sobre o estado **resultante** (para o PATCH, o estado atual mesclado com o corpo). Em criação/PATCH qualquer *erro* (não *aviso*) → 422 `invalid_analysis_definition` com a lista de problemas e **nada é gravado**. Verificações (§4.5.3).
- **Criar:** uma transação: `INSERT analyses` → `INSERT analysis_steps` (`step_order = 1`, `step_type = 'query'`, `definition = {"sql","params"}` via `$n::jsonb`) → `INSERT profile_analyses` para cada `profile_ids` (deduplicados). `data_source_id` e `profile_ids` inexistentes → 422 `invalid_reference` (lista os ausentes; rollback total). `created_by` = e-mail do admin. **Não** vincula nenhum perfil sozinha (nem o `admin` do seed): só os `profile_ids` enviados (decisão 2026-10-08, §10).
- **Alterar (PATCH):** só os campos enviados. `parameters`, quando enviado, **substitui** o objeto inteiro (não faz merge de chaves). `step` mescla `sql`/`params` sobre o step atual (o primeiro); se a análise legada não tiver step, o PATCH exige `sql` e cria o step 1. **`analyses.updated_at = NOW()` em toda alteração, mesmo que só o step mude** (o `analysis_steps.updated_at` também), pois ele entra na chave do cache (ARQUITETURA.md §3.2). Alterar `data_source_id` exige que o novo exista.
- **Mudar `is_active`** não precisa de tratamento extra: o `/mcp` lê `analyses` a cada chamada (ela some/volta no `list_tools()` e a execução responde `ANALYSIS_NOT_FOUND`).
- **Excluir:** 409 `analysis_has_history` se houver linha em `execution_history` (`SELECT 1 ... LIMIT 1`, há índice em `analysis_id`) — a mensagem orienta desativar. Sem histórico: `DELETE` apaga `analysis_steps` e `profile_analyses` em cascata. `ForeignKeyViolationError` por corrida também vira 409.
- **Substituir perfis:** valida a existência dos `profile_ids` (422 `invalid_reference`), `DELETE` + `INSERT` em transação, ids duplicados tolerados. **Não** altera `analyses.updated_at`: permissão não entra na chave do cache e é recalculada a cada chamada (F12) — mexer nele só descartaria cache à toa (§11, P3). Efeito nas permissões é imediato.
- **Invalidar cache:** `UPDATE analyses SET updated_at = NOW()` (decisão 2026-10-08): as chaves antigas (`updated_at` faz parte do hash) deixam de ser alcançáveis; os registros velhos saem por TTL/LRU do `InMemoryBackend`, sem mudar o contrato do `CacheBackend` e igual num futuro Redis. Consequência a documentar: a memória das entradas antigas só é liberada na expiração. Vale para análise com `cache_frequency = 'none'` (no-op inofensivo).

#### 4.5.3 Verificações da definição (`validate_analysis_definition`)

Função pura em `services/analysis_admin_service.py` (ou módulo próprio), reaproveitando as validações do engine — fonte única de verdade:

| Código | Severidade | Verificação |
|---|---|---|
| `invalid_parameters_schema` | erro | `validate_schema(parameters)` (tipos, `required` bool, `enum`/`min`/`max` compatíveis) |
| `invalid_cache_frequency` | erro | `cache_frequency` ∈ {`hourly`,`daily`,`weekly`,`none`} (as chaves de `_TTL_BY_FREQUENCY` do `CacheService`, sem duplicar a lista) |
| `missing_step` | erro | a análise não tem step (só ocorre em análise legada em `/validate`) |
| `sql_not_allowed` | erro | `validate_select_only(sql)` (só `SELECT`, sem `;`, sem DML/DDL) |
| `unknown_step_param` | erro | nome em `step.params` ausente de `analyses.parameters` (o engine levantaria `KeyError`) |
| `placeholder_not_declared` | erro | `:nome` presente no SQL e ausente de `step.params` (não seria traduzido) |
| `param_not_in_sql` | erro | nome em `step.params` sem `:nome` no SQL (excesso de valores no bind; também a regra para rodar nos 4 bancos — F11 §8.4, F9 §8.4) |
| `duplicate_step_param` | erro | nome repetido em `step.params` |
| `data_source_not_found` | erro | `data_source_id` não existe |
| `data_source_inactive` | aviso | o data source está inativo (a execução vai falhar com `DATA_SOURCE_UNAVAILABLE`) |
| `parameter_not_used` | aviso | parâmetro de `analyses.parameters` que não está em `step.params` (o cliente seria obrigado a informar algo sem efeito) |

`extract_placeholders(sql)` (novo em `schemas/sql_validation.py`) lista os `:nome` do SQL **depois de remover literais, identificadores entre aspas e comentários** (o mesmo `_STRIP_PATTERN` de `validate_select_only`, **sem** remover os placeholders), ignorando `::tipo`.

`POST /admin/analyses/{id}/validate` executa as mesmas verificações sobre a análise **salva** e devolve `valid = (errors == [])`; sempre 200 (para analyses legadas, cadastradas por INSERT, com problemas). **Estático apenas** (decisão 2026-10-08): não conecta ao data source nem executa `COUNT(*)`. Colunas/tabelas inexistentes só aparecem ao executar.

### 4.6 Erros (formato `{"error": "<slug>", "message": "<texto em português>"}`)

Além dos slugs da F23 (`unauthorized`, `forbidden`, `profile_not_found`, `invalid_reference`, `internal_error`):

| HTTP | `error` | Quando |
|---|---|---|
| 404 | `data_source_not_found` · `analysis_not_found` | Recurso inexistente |
| 409 | `data_source_name_already_exists` · `analysis_name_already_exists` | Violação de unicidade (`data_sources.name`, `analyses.name`); também por corrida (`UniqueViolationError`) |
| 409 | `data_source_has_analyses` | Exclusão de data source com análises — desativar |
| 409 | `analysis_has_history` | Exclusão de análise com `execution_history` — desativar |
| 422 | `invalid_connection_config` | `connection_config` incompleto, com chave desconhecida ou valor inválido (§4.4.1) |
| 422 | `unsupported_data_source_type` | `type` fora do `AdapterFactory` |
| 422 | `invalid_analysis_definition` | Alguma verificação de severidade *erro* da §4.5.3 falhou (a mensagem lista os problemas) |
| 422 | `invalid_reference` | `data_source_id` / `profile_ids` inexistentes (lista os ausentes) |
| 422 | (padrão FastAPI) | Corpo/query inválidos (PATCH vazio, UUID malformado, `limit` fora de 1–200) |

O contrato `error_code`/`retryable` da F14 continua restrito ao `/mcp`. As mensagens **nunca** incluem senha, `connection_config` completo ou texto de exceção de driver.

### 4.7 Banco de Dados

**Sem DDL novo**, sem `ALTER`, sem índice novo (sem evidência de `EXPLAIN`, mesmo critério da F15). Consultas principais (parametrizadas `$n`):
- Contagem de análises por data source na listagem: `LEFT JOIN`/subconsulta `COUNT(*)` por `data_source_id` (sem índice dedicado; volume baixo).
- Existência de histórico: `SELECT 1 FROM execution_history WHERE analysis_id = $1 LIMIT 1` (usa `idx_execution_history_analysis`).
- Invalidação de cache em lote: `UPDATE analyses SET updated_at = NOW() WHERE data_source_id = $1`.
- JSONB: `INSERT ... VALUES ($n::jsonb)` com `json.dumps` do dict; `connection_config` lido com o `_load_json` defensivo existente.

### 4.8 Interfaces (assinaturas)

```python
# services/data_source_admin_service.py
class DataSourceAdminService:
    def __init__(self, db: PostgreSQLAdapter, repo: DataSourceRepository, pool_invalidator) -> None
    async def list_types(self) -> list[DataSourceType]
    async def list_data_sources(self, q, type, is_active, limit, offset) -> Page[DataSourceSummary]
    async def create_data_source(self, data: DataSourceCreate, actor: AuthenticatedUser) -> DataSourceDetail
    async def get_data_source(self, ds_id: UUID) -> DataSourceDetail
    async def update_data_source(self, ds_id, data: DataSourceUpdate, actor) -> DataSourceDetail
    async def delete_data_source(self, ds_id, actor) -> None
    async def test_saved(self, ds_id: UUID) -> ConnectionTestResult
    async def test_config(self, data: ConnectionTestBody) -> ConnectionTestResult

# services/analysis_admin_service.py
class AnalysisAdminService:
    def __init__(self, db: PostgreSQLAdapter, analyses: AnalysisRepository,
                 data_sources: DataSourceRepository, profiles: ProfileRepository) -> None
    async def list_analyses(self, q, data_source_id, is_active, limit, offset) -> Page[AnalysisSummary]
    async def create_analysis(self, data: AnalysisCreate, actor) -> AnalysisDetail
    async def get_analysis(self, analysis_id) -> AnalysisDetail
    async def update_analysis(self, analysis_id, data: AnalysisUpdate, actor) -> AnalysisDetail
    async def delete_analysis(self, analysis_id, actor) -> None
    async def set_profiles(self, analysis_id, profile_ids, actor) -> AnalysisDetail
    async def validate(self, analysis_id) -> ValidationReport
    async def invalidate_cache(self, analysis_id, actor) -> InvalidateResult
```

Exceções de domínio (herdam de `AdminError`, em `schemas/admin.py`): `DataSourceNotFoundError`, `AnalysisNotFoundError` *(nome distinto do `AnalysisNotFoundError` do engine — usar `AdminAnalysisNotFoundError`)*, `DataSourceNameAlreadyExistsError`, `AnalysisNameAlreadyExistsError`, `DataSourceHasAnalysesError`, `AnalysisHasHistoryError`, `InvalidConnectionConfigError`, `UnsupportedDataSourceTypeError`, `InvalidAnalysisDefinitionError`.

---

## 5. Critérios de Aceitação

```gherkin
Feature: API administrativa — data sources e analyses

Scenario: Controle de acesso
  When Chamo qualquer rota nova sem token / com token de não-admin
  Then Recebo 401 unauthorized / 403 forbidden (varredura de todas as rotas /admin/*)

Scenario: Cadastrar data source
  When POST /admin/data-sources {name, type:"postgresql", connection_config completo}
  Then Recebo 201 sem o campo password em connection_config (has_password=true)
  And No banco, connection_config.password está cifrada com Fernet e decifra para a senha enviada

Scenario: Configuração inválida
  When Envio type desconhecido, chave obrigatória ausente, porta fora de 1–65535, chave desconhecida,
       sslmode inválido ou Oracle com service_name e sid juntos
  Then Recebo 422 (unsupported_data_source_type / invalid_connection_config) e nada é gravado

Scenario: Editar sem reenviar a senha
  Given Um data source com senha cifrada
  When PATCH {"connection_config":{"host":"novo-host"}}
  Then Só o host muda, a senha cifrada permanece idêntica e a resposta não a contém
  When PATCH {"connection_config":{"password":"outra"}}
  Then A senha é recifrada

Scenario: Editar conexão derruba o pool
  Given Um data source com adapter já aberto em AnalysisService._adapters
  When PATCH muda host (ou is_active para false)
  Then O adapter é removido e fechado, e a próxima execução usa o config novo (ou falha com DATA_SOURCE_UNAVAILABLE)
  And O updated_at das analyses desse data source é atualizado (cache não serve o resultado antigo)

Scenario: Testar conexão
  When POST /admin/data-sources/{id}/test-connection com banco acessível
  Then 200 {"ok":true,...}
  When O banco está fora / credencial errada / host inexistente / demora mais de 10 s
  Then 200 {"ok":false,"message":<por categoria>,"error_type":...} sem texto cru do driver nem senha
  When POST /admin/data-sources/test-connection com {type, connection_config}
  Then Testa sem gravar nada

Scenario: Excluir data source
  Given Um data source sem analyses
  When DELETE
  Then 204 e o pool, se existir, é fechado
  Given Um data source com analyses (ativas ou inativas)
  When DELETE
  Then 409 data_source_has_analyses orientando desativar

Scenario: Criar análise completa
  Given Um data source e o perfil "Comercial"
  When POST /admin/analyses com step {sql com :data_inicial, params:["data_inicial"]}, parameters coerentes e profile_ids
  Then 201 com step e perfis; análise + step + vínculos foram gravados numa transação
  And Usuário do perfil vê a tool em list_tools() e executa sem nenhum passo manual
  And A análise NÃO é vinculada a nenhum perfil que não esteja em profile_ids (nem ao "admin")

Scenario: Definição inválida na criação
  When SQL com INSERT / ';' / SQL sem SELECT, params com nome fora de parameters,
       :placeholder ausente de params, param ausente do SQL, parameters com type inválido,
       cache_frequency inválido
  Then 422 invalid_analysis_definition listando os problemas e nada é gravado (rollback)
  When data_source_id ou algum profile_id não existe
  Then 422 invalid_reference listando os ids e nada é gravado

Scenario: Editar análise nunca serve cache antigo
  Given Uma execução em cache (cache_frequency daily)
  When PATCH altera só step.sql
  Then analyses.updated_at (e analysis_steps.updated_at) mudam e a execução seguinte consulta o banco

Scenario: PATCH parcial coerente
  When PATCH {"step":{"sql":"..."}} sem enviar params
  Then Os params existentes são mantidos e a combinação é revalidada
  When PATCH {"parameters":{...}} remove um parâmetro usado em step.params
  Then 422 invalid_analysis_definition (unknown_step_param)

Scenario: Listagem administrativa
  Then GET /admin/analyses inclui análises inativas, filtra por q, data_source_id e is_active, e pagina

Scenario: Excluir análise
  Given Uma análise sem histórico
  When DELETE
  Then 204 e step e vínculos somem em cascata
  Given Uma análise com execution_history
  When DELETE
  Then 409 analysis_has_history orientando desativar

Scenario: Vincular perfis
  When PUT /admin/analyses/{id}/profiles {profile_ids}
  Then O conjunto é substituído e as permissões mudam imediatamente; updated_at da análise não muda

Scenario: Validar análise salva (estático)
  Given Uma análise criada por INSERT manual com um placeholder fora de params
  When POST /admin/analyses/{id}/validate
  Then 200 {"valid":false,"errors":[{"code":"placeholder_not_declared",...}]} sem tocar no data source
  Given Data source inativo
  Then Aparece como warning data_source_inactive e valid continua true

Scenario: Invalidar cache
  When POST /admin/analyses/{id}/cache/invalidate
  Then updated_at = NOW() e a execução seguinte não reaproveita o cache anterior

Scenario: Segredos
  Then Nenhuma resposta, log ou mensagem de erro contém connection_config.password (cifrada ou não) nem o SQL de log admin_action
```

---

## 6. Testes

### 6.1 Testes Unitários / de Rota

Padrão da F23 (`tests/test_admin_api.py`, `tests/admin_fakes.py`): FastAPI mínimo com `include_router` + `dependency_overrides`, repositórios fake em memória, sem lifespan nem banco; `FERNET_KEY` de teste (`tests/test_crypto.py` já usa).

```python
class TestSweepAuthorization:         # a varredura de /admin/* da F23 passa a incluir as rotas novas (401/403)
class TestDataSourceTypes:            # GET /types; validate_connection_config por tipo (obrigatórias, port, sslmode,
                                      # Oracle service_name xor sid, pool_min/max, chave desconhecida)
class TestDataSourceRoutes:           # list/filtros/paginação, create (cifra), get (sem password, has_password),
                                      # patch merge (senha preservada/recifrada, null em opcional/obrigatória),
                                      # delete (409 com analyses), nome duplicado
class TestDataSourceSideEffects:      # PATCH config/is_active -> invalidate_data_source + bump updated_at das analyses;
                                      # PATCH só name -> nada; delete -> invalidate
class TestConnectionTest:             # ok / connect falha / test_connection False / timeout 10 s (wait_for) /
                                      # adapter sempre desconectado (finally) / sem retry / mensagem sem texto do driver
class TestAnalysisServiceInvalidation:# invalidate_data_source: remove, desconecta, idempotente, erro no disconnect só logado
class TestAnalysisDefinition:         # cada código da tabela §4.5.3 (erro/aviso), extract_placeholders
                                      # (ignora literais, comentários, ::cast, aspas)
class TestAnalysisRoutes:             # list inclui inativas, create (+step+perfis), get, patch parcial (step mesclado,
                                      # parameters substituído), delete (409 histórico), nome duplicado
class TestAnalysisCache:              # updated_at muda em PATCH de step; PUT profiles não muda; invalidate muda
class TestAnalysisAtomicity:          # falha no vínculo/perfil -> nada gravado (rollback)
class TestValidateEndpoint:           # análise legada com problemas -> valid=false; só estático (adapter nunca criado)
class TestNoSecretsInLogs:            # caplog: sem password/cifra/SQL em admin_action e nos logs do teste de conexão
```

### 6.2 Integração (Config DB real)

Arquivo no padrão de `tests/test_admin_integration.py` (pula sozinho sem banco ou sem `users.is_admin`): criar análise com perfil inexistente → rollback real (nenhuma linha em `analyses`/`analysis_steps`); `INSERT ... $n::jsonb` do step e do `connection_config` lidos de volta; unicidade → 409; cascata de `DELETE` análise (steps, vínculos); FK de `analyses.data_source_id` e de `execution_history.analysis_id` → 409; **ciclo completo**: criar data source (apontando para o próprio Postgres do compose) + análise + vincular perfil + executar via `AnalysisService`, editar o SQL e verificar que o cache não serve o antigo; PATCH de `connection_config` seguido de execução usando o pool novo.

### 6.3 Checklist de Testes
- [x] 401/403 em todas as rotas novas (varredura)
- [x] Senha cifrada ao gravar, nunca devolvida/logada; PATCH preserva/recifra corretamente
- [x] Validação de `connection_config` por tipo; chaves desconhecidas recusadas
- [x] `invalidate_data_source` ao editar config/`is_active` e ao excluir; bump de `updated_at` das analyses
- [x] Teste de conexão (salvo e prévio): ok, falha por categoria, timeout, adapter sempre fechado, sem texto do driver
- [x] Criação de análise atômica; análise criada executa pelo engine sem passo manual
- [x] Todas as verificações da §4.5.3 (erro e aviso) em criar, PATCH e `/validate`
- [x] `updated_at` atualizado em todo PATCH de análise/step e no `cache/invalidate`; não muda em `PUT .../profiles`
- [x] Exclusão híbrida: 409 com análises (data source) e com histórico (análise)
- [x] Listagem administrativa inclui inativas; `AnalysisRepository.get_by_id/get_all` inalterados (regressão do `/mcp`)
- [x] Integração com Postgres real (rollback, JSONB, cascata, ciclo executar → editar → executar)
- [x] Suíte completa (571+) passando com `.venv`
- [ ] Manual: pelo frontend/cliente HTTP, cadastrar data source + análise + perfil, emitir token e executar a tool num cliente MCP real; editar o SQL e a conexão e ver o efeito imediato

---

## 7. Mudanças na Configuração

Sem variáveis novas no `.env` (o limite de 10 s do teste de conexão é constante no serviço). Sem nova dependência. Sem `ALTER TABLE`/DDL. A `FERNET_KEY` já é obrigatória (F4): **a API cifra com a mesma chave que o `AnalysisService` usa para decifrar** — trocar a chave invalida as senhas já gravadas (comportamento existente, DATABASE_SCHEMA.md §4).

## 8. Documentação

### 8.1 Como a feature aparece no MCP
Não aparece: é API HTTP separada do `/mcp`. Efeitos indiretos imediatos: análises criadas/editadas/desativadas e vínculos de perfil refletem em `list_tools()`/`call_tool()` na chamada seguinte; edição de SQL/parâmetros nunca serve cache antigo; edição de conexão vale na execução seguinte.

### 8.2 Como o usuário usa
O frontend (fora de escopo) autentica como administrador (`POST /auth/token`) e usa `Authorization: Bearer`. Fluxo típico: `GET /admin/data-sources/types` → `POST /admin/data-sources/test-connection` (prévio) → `POST /admin/data-sources` → `POST /admin/analyses` (com `step` e `profile_ids`) → `POST /admin/analyses/{id}/validate` quando quiser rechecar.

### 8.3 Como outros desenvolvedores estenderão
Novo tipo de data source = adapter novo no `AdapterFactory` **e** uma entrada em `schemas/data_source_types.py` (um teste garante que os dois conjuntos de tipos coincidem). Nova verificação de definição = uma linha na tabela de `validate_analysis_definition`. A F25 acrescenta `GET /admin/analyses/{id}/executions` no router de analyses.

---

## 9. Checklist de Implementação

**Código:**
- [x] `schemas/data_source_types.py` + `extract_placeholders`
- [x] Repositórios (`data_source_repo`, `analysis_repo`) com `db` opcional
- [x] `AnalysisService.invalidate_data_source`
- [x] `services/data_source_admin_service.py`, `services/analysis_admin_service.py`
- [x] Modelos e exceções em `schemas/admin.py`
- [x] `routes/admin_data_sources.py`, `routes/admin_analyses.py`, `routes/dependencies.py`, `main.py`
- [x] Docstrings

**Documentação (ao concluir):**
- [x] Preencher §12; marcar F24 como 🟩 no ROADMAP e no `.claude/CLAUDE.md`
- [x] ARQUITETURA.md §2.4 e DATABASE_SCHEMA.md §2.1/§2.2 atualizados

**QA:**
- [x] Suíte completa passando (com `.venv`)
- [ ] Validação manual (§6.3)
- [ ] Code review

---

## 10. Decisões (2026-10-08)

| # | Decisão | Origem |
|---|---|---|
| 1 | `cache/invalidate` = `UPDATE analyses SET updated_at = NOW()` (sem mudar o `CacheBackend`) | Confirmada 2026-10-08 |
| 2 | `POST /admin/analyses` vincula só os `profile_ids` enviados; nada de vínculo implícito ao perfil `admin` | Confirmada 2026-10-08 |
| 3 | `/validate` é só estático (sem dry-run no data source) | Confirmada 2026-10-08 |
| 4 | `connection_config` no PATCH é mesclado (senha só regravada se enviada); teste da conexão salva (`/{id}/test-connection`) e prévio (`/test-connection`) | Confirmada 2026-10-08 |
| 5 | Exclusão híbrida: data source com análises e análise com histórico → 409 orientando desativar | ADR-008 |
| 6 | Reuso das validações do engine (`validate_schema`, `validate_select_only`) como fonte única; a API recusa o que o engine recusaria | ARQUITETURA.md §2.4 |
| 7 | Importação tardia de `mcp_transport.tools.analysis_service` só para invalidar o pool, injetada como dependência substituível nos testes | Confirmada 2026-10-08 (§4.3) |
| 8 | Erros do teste de conexão sem texto cru do driver (categoria + `error_type`); limite de 10 s, sem retry, adapter temporário | Confirmada 2026-10-08 |
| 9 | `type` do data source não é alterável no PATCH (trocar = criar outro data source) | Confirmada 2026-10-08 |
| 10 | PATCH de `connection_config`/`is_active` atualiza `updated_at` das analyses do data source (mesma transação) | Confirmada 2026-10-08 |
| 11 | `PUT /admin/analyses/{id}/profiles` não atualiza `analyses.updated_at` | Confirmada 2026-10-08 |
| 12 | Chave desconhecida em `connection_config` → 422 | Confirmada 2026-10-08 |
| 13 | Criar/PATCH recusam definição inconsistente (422); só `/validate` relata análises legadas | Confirmada 2026-10-08 |
| 14 | `param_not_in_sql` é erro, não aviso | Confirmada 2026-10-08 |
| 15 | Testar conexão de data source inativo é permitido | Confirmada 2026-10-08 |
| 16 | Mensagem do teste de conexão não inclui o texto da exceção do driver | Confirmada 2026-10-08 |

## 11. Pontos em aberto

Nenhum. Os 8 pontos propostos na escrita da spec foram confirmados pelo responsável em 2026-10-08 (padrões adotados, mantidos como decisões 9 a 16 na §10):

| # | Ponto | Resolução |
|---|---|---|
| ~~P1~~ | `type` do data source alterável no PATCH? | ✅ Não (decisão 9) |
| ~~P2~~ | Editar `connection_config`/`is_active` atualiza `updated_at` das analyses do data source? | ✅ Sim, na mesma transação do PATCH (decisão 10) |
| ~~P3~~ | `PUT /admin/analyses/{id}/profiles` atualiza `analyses.updated_at`? | ✅ Não — permissão não entra na chave do cache; "`updated_at` sempre atualizado" vale para alterações de definição (decisão 11) |
| ~~P4~~ | Chave desconhecida em `connection_config` | ✅ 422 (decisão 12) |
| ~~P5~~ | Salvar análise com SQL/parâmetros inconsistentes | ✅ Não: criar/PATCH recusam com 422; só `/validate` relata legadas (decisão 13) |
| ~~P6~~ | `param_not_in_sql` é erro | ✅ Erro (decisão 14) |
| ~~P7~~ | Testar conexão de data source inativo | ✅ Permitido (decisão 15) |
| ~~P8~~ | Mensagem do teste sem texto da exceção do driver | ✅ Sim, detalhe só no log (decisão 16) |

## 12. Implementação

**Resultado (2026-10-08):** 672/672 testes ✅ com `.venv` (571 anteriores + 95 de rota/serviço em `tests/test_admin_data_sources_analyses.py` com repositórios em memória de `tests/admin_fakes.py` + 6 de integração em `tests/test_admin_data_sources_analyses_integration.py` contra o Postgres do compose, incluindo o ciclo criar → executar → editar SQL → executar → editar conexão → executar; 1 skip pré-existente).

**Arquivos novos:** `schemas/data_source_types.py`, `services/data_source_admin_service.py`, `services/analysis_admin_service.py`, `routes/admin_data_sources.py`, `routes/admin_analyses.py`. **Modificados:** `schemas/admin.py` (modelos + 9 exceções), `schemas/sql_validation.py` (`extract_placeholders`), `repositories/data_source_repo.py`, `repositories/analysis_repo.py` (`get_steps` ganhou `db` opcional; `get_by_id`/`get_all` inalterados), `repositories/profile_repo.py` (`existing_ids` aceita `profiles`), `services/analysis_service.py` (`invalidate_data_source`), `services/cache_service.py` (`CACHE_FREQUENCIES`), `routes/dependencies.py`, `main.py`.

**Desvios em relação ao desenho:**
- Os dois serviços recebem também o `UserRepository` (para `created_by` = e-mail do admin, como na F23).
- **PATCH de análise só revalida a definição quando toca nela** (`parameters`, `cache_frequency`, `data_source_id` ou `step`). Renomear, mudar `description` ou ativar/desativar não é bloqueado por inconsistência pré-existente — assim uma análise legada quebrada (INSERT manual) pode ser desativada pela API. O `updated_at` continua sendo atualizado em toda alteração.
- **Achado na integração:** `pool_min_size` sem `pool_max_size` menor que o `PG_POOL_MIN_SIZE` do `.env` (padrão 10) fazia o asyncpg recusar o pool só na primeira execução. `validate_connection_config` (PostgreSQL) agora valida o par **efetivo** (valor informado ou padrão do `.env`) e responde 422 com a explicação.
- O teste de integração usa `SELECT :n::int` (o PostgreSQL infere `text` para um `$1` sem tipo).

**Como rodar:** `.venv/bin/python -m pytest tests` (a integração usa o Config DB do `.env`, `localhost:5433`, e pula sozinha sem banco).
