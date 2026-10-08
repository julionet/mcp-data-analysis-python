# F25 — API Administrativa: Histórico de Execuções

## Feature Spec

**ID:** F25
**Nome:** API Administrativa — histórico de execuções (`/admin/executions`) e estatísticas
**Prioridade:** 🟡 Média
**Esforço Estimado:** 1.5d
**Status:** 🟩 Done (2026-10-08) — validação manual pendente (§6.3); índice `(analysis_id, executed_at DESC)` **proposto, aguardando decisão** (§12)

> **Origem dos requisitos:** NEGOCIO.md v1.12 (RF6 "Histórico (F25)", UC4 cenário "Administrador consulta o histórico de execuções"), ARQUITETURA.md v1.26 (§2.4 "F25", §3.6, ADR-008), FEATURES_ROADMAP.md v1.22, DATABASE_SCHEMA.md (§2.5 `execution_history`, índices §5, §8) e as specs `features/F23_API_ADMIN_USUARIOS_PERFIS.md` (convenções comuns, `require_admin`, `AdminRoute`, `Page`) e `features/F24_API_ADMIN_DATA_SOURCES_ANALYSES.md` (o atalho `GET /admin/analyses/{id}/executions` entra no router de analyses). Esta spec cobre só a **F25**.

---

## 1. Visão

Hoje o histórico de execuções (`execution_history`, F8/F12/F14) só é consultável por SQL direto no Config DB — e `ExecutionRepository.get_all(limit)` não tem filtro nem paginação. A F25 entrega, na API `/admin/*`, a **consulta somente-leitura** ao histórico: listagem filtrada e paginada (com os parâmetros de cada execução), detalhe de uma execução e estatísticas por período, para o futuro frontend de gestão e para a auditoria de "quem executou o quê, quando e com que resultado".

## 2. Objetivo

Permitir que um administrador responda, sem acesso ao banco: *quais execuções falharam hoje e por quê*, *o que o usuário X executou*, *com que parâmetros a análise Y foi chamada*, *qual a taxa de cache hit e o p95 do período* — sem risco de uma consulta derrubar o Config DB (paginação obrigatória, janela de estatística limitada).

**Métrica de Sucesso:**
- ✅ Todas as rotas novas exigem `require_admin` (a varredura de rotas `/admin/*` da F23 cobre as novas: 401 sem token, 403 sem `is_admin`)
- ✅ `GET /admin/executions` filtra por análise, usuário, status, código de erro, cache, período, tempo mínimo e parâmetros, ordena por `executed_at` desc e pagina (`{items,total,limit,offset}`)
- ✅ Cada item traz nome da análise e do usuário (execuções pré-F12 têm `user` nulo), os `parameters`, tempo, linhas e bytes
- ✅ `GET /admin/executions/{id}` devolve o detalhe completo, incluindo `error_message`
- ✅ `GET /admin/executions/stats` devolve contagem por status e por código de erro, taxa de cache hit, tempo médio/p95/máx e as análises e usuários mais frequentes do período
- ✅ `GET /admin/analyses/{id}/executions` é o atalho por análise (404 se a análise não existe)
- ✅ Rotas **somente leitura**: nenhuma escrita em `execution_history` nem em outra tabela; sem DDL
- ✅ `parameters` e `error_message` (dado do cliente / texto de erro) nunca vão para log
- ✅ Os 672 testes atuais continuam passando; `/mcp`, `/auth/*` e as rotas da F23/F24 inalterados

## 3. Contexto

**Depende de:** F23 (`require_admin`, `AdminRoute`, `AdminError`, `Page`, `routes/dependencies.py`), F24 (router `/admin/analyses` e `AnalysisRepository.get_any_by_id`), F8/F12/F14 (conteúdo e colunas de `execution_history`)
**É dependência de:** F16 (documentação), F17 (cobertura de testes)

**Estado do código (verificado antes de escrever):**
- `ExecutionRepository` (`src/repositories/execution_repo.py`) tem `create` (usado pelo `AuditService`) e `get_all(limit)` — sem filtro, offset, join nem contagem. `get_all` só é chamado por `AuditService.get_execution_history` ("método interno para uso futuro", sem chamador) e por `tests/test_execution_repo.py`.
- `execution_history`: `id`, `analysis_id` (NOT NULL, FK), `user_id` (FK nula — `NULL` em linhas pré-F12), `parameters` JSONB, `status` ∈ `success`/`volume_exceeded`/`error`/`timeout`, `execution_time_ms`, `rows_affected`, `result_size_bytes`, `error_message`, `result_location` (reservada, sempre `NULL`), `executed_at` **`TIMESTAMP` sem fuso** (`DEFAULT NOW()`), `cached`, `error_code` (`NULL` sem erro e pré-F14). Índices simples: `analysis_id`, `executed_at`, `user_id`. Sem retenção: a tabela cresce sem limite.
- O `AuditService` só grava `error_message`/`error_code` quando `status ∈ {error, timeout}`; em `volume_exceeded`, `rows_affected`/`result_size_bytes` guardam a **estimativa** (DATABASE_SCHEMA.md §2.5).
- `parameters` é gravado **como o cliente enviou, antes da validação** (sem defaults resolvidos) e pode divergir do schema atual da análise; pode conter dado sensível.
- `PostgreSQLAdapter.execute_query(query, params: dict, scalar)` liga os valores do dict **por posição** (`*params.values()`); o asyncpg não tem codec JSONB (JSONB chega como `str` → `json.loads`, como o `_load_json` de `analysis_repo.py`; filtro de contenção precisa de `$n::jsonb`).
- Padrão de filtro opcional já usado nas listagens da F23/F24: `($n::tipo IS NULL OR coluna = $n)` com o dict de filtros em ordem; `like_pattern` em `repositories/sql_helpers.py` para `ILIKE`.
- `AdminRoute` converte `AdminError` em `{"error","message"}`; 422 de validação do FastAPI mantém o formato padrão `{"detail":[...]}` (F23, decisão 15).

---

## 4. Descrição Técnica

### 4.1 Componentes Afetados

```
Componentes criados/modificados:
├─ repositories/execution_repo.py    (modificado) + search(filtros, limit, offset), count(filtros), get_detail(id),
│                                     stats(from, to, top) — somente leitura; `get_all` REMOVIDO (substituído por search)
├─ services/execution_admin_service.py (novo) montagem dos modelos, validação do período e do filtro de parâmetros
├─ services/audit_service.py         (modificado) remove `get_execution_history` (sem chamador; era o "uso futuro" que a F25 entrega)
├─ schemas/admin.py                  (modificado) modelos Execution* + exceções ExecutionNotFoundError,
│                                     InvalidPeriodError, InvalidParametersFilterError
├─ routes/admin_executions.py        (novo) /admin/executions
├─ routes/admin_analyses.py          (modificado) + GET /admin/analyses/{id}/executions
├─ routes/dependencies.py            (modificado) + get_execution_admin_service()
├─ main.py                           (modificado) include_router do novo router
├─ tests/test_execution_repo.py      (modificado) get_all → search/count
└─ (sem mudança) schema.sql / DDL, CORS (só GET), requirements.txt
```

### 4.2 Autorização e convenções

Idênticas à F23 (§4.2 e §4.3 daquela spec): router com `route_class=AdminRoute` e `dependencies=[Depends(require_admin)]`; serviço injetado por `routes/dependencies.py` sobre `config_db_adapter` (import tardio, substituível por `dependency_overrides`); paginação `limit` (padrão 50, máx. 200) / `offset`, resposta `{items,total,limit,offset}`; erros `{"error","message"}`; UUID malformado, enum inválido e `limit` fora de 1–200 → 422 padrão do FastAPI.

Diferenças por ser leitura: **não há evento `admin_action`** (a F23/F24 logam só escritas) e o serviço não usa o ator. O atalho em `/admin/analyses` reaproveita o mesmo serviço. Nunca logar `parameters`, `error_message` nem o filtro `parameters` recebido (§4.7).

### 4.3 Endpoints

| Método | Path | Query | Sucesso | Erros |
|---|---|---|---|---|
| GET | `/admin/executions` | filtros (abaixo), `limit`, `offset` | 200 `Page[ExecutionSummary]` | 401, 403, 422 |
| GET | `/admin/executions/stats` | `from`, `to`, `analysis_id`, `user_id`, `top` | 200 `ExecutionStats` | 401, 403, 422 `invalid_period` |
| GET | `/admin/executions/{id}` | — | 200 `ExecutionDetail` | 404 `execution_not_found` |
| GET | `/admin/analyses/{id}/executions` | mesmos filtros de `/admin/executions`, **exceto** `analysis_id` | 200 `Page[ExecutionSummary]` | 404 `analysis_not_found` |

(`/stats` é declarada **antes** de `/{id}` e `id` é `UUID`, então não colidem.)

**Filtros de `GET /admin/executions`** (todos opcionais, combinados com `AND`):

| Query | Tipo | Semântica |
|---|---|---|
| `analysis_id` | UUID | igualdade |
| `user_id` | UUID | igualdade (execuções pré-F12 têm `user_id` nulo e nunca casam) |
| `status` | enum `success` \| `volume_exceeded` \| `error` \| `timeout` | igualdade; outro valor → 422 |
| `error_code` | enum dos 7 códigos da F14 (`ANALYSIS_NOT_FOUND`, `INVALID_PARAMETERS`, `INVALID_ANALYSIS_CONFIG`, `DATA_SOURCE_UNAVAILABLE`, `QUERY_TIMEOUT`, `QUERY_FAILED`, `INTERNAL_ERROR`) | igualdade; outro valor → 422 |
| `cached` | bool | igualdade |
| `from` | datetime ISO 8601 | `executed_at >= from` (inclusivo) |
| `to` | datetime ISO 8601 | `executed_at < to` (exclusivo — janelas contíguas não duplicam linhas) |
| `min_time_ms` | int ≥ 0 | `execution_time_ms >= min_time_ms` (linhas com tempo `NULL` não casam) |
| `parameters` | string JSON de um **objeto** | contenção JSONB: `parameters @> $n::jsonb` (ex.: `{"regiao":"SP"}`); ver §4.5 |

`from`/`to` são aliases do `Query` (`Query(alias="from")`; `from` é palavra reservada no Python). `from >= to` quando ambos informados → 422 `invalid_period`.

**Fuso:** `executed_at` é `TIMESTAMP` sem fuso, gravado com `NOW()` na sessão do Postgres (contêiner: UTC). `from`/`to` **naive** são comparados diretamente; **com offset** são convertidos para UTC e passados naive (premissa: sessão do Config DB em UTC — mesmo ambiente dos compose; um teste de integração falha se `SHOW timezone` não for UTC — decisão 11). `executed_at` é devolvido como a coluna está (ISO 8601 naive), igual a `created_at`/`updated_at` das demais rotas admin.

### 4.4 Modelos (`schemas/admin.py`)

```python
class ExecutionAnalysisRef(BaseModel):
    id: UUID
    name: str

class ExecutionUserRef(BaseModel):          # null quando user_id é NULL (pré-F12)
    id: UUID
    name: str
    email: str                              # users.external_id (str, não EmailStr: o login "admin" do seed não é e-mail)

class ExecutionSummary(BaseModel):
    id: UUID
    analysis: ExecutionAnalysisRef
    user: ExecutionUserRef | None
    status: str
    error_code: str | None
    cached: bool
    parameters: dict[str, Any]              # {} se NULL no banco
    execution_time_ms: int | None
    rows_affected: int | None
    result_size_bytes: int | None
    executed_at: datetime

class ExecutionDetail(ExecutionSummary):
    error_message: str | None               # só preenchido em status error/timeout (AuditService)
    # result_location é reservada (sempre NULL em V1.0) e NÃO é exposta

class StatusCounts(BaseModel):              # sempre os 4 status, zerados quando ausentes
    success: int; volume_exceeded: int; error: int; timeout: int

class TimeStats(BaseModel):
    avg: float | None; p95: float | None; max: int | None   # None sem execuções success com tempo

class ExecutionTopAnalysis(BaseModel): analysis_id: UUID; name: str; count: int
class ExecutionTopUser(BaseModel):     user_id: UUID; name: str; email: str; count: int

class ExecutionStats(BaseModel):
    period: dict[str, datetime]             # {"from":..., "to":...} efetivos (com os padrões aplicados)
    total: int
    by_status: StatusCounts
    by_error_code: dict[str, int]           # só códigos presentes; execuções com error_code NULL não entram
    cache: dict                             # {"hits": int, "success": int, "hit_rate": float | None}
    execution_time_ms: dict[str, TimeStats] # {"cache_hit": ..., "cache_miss": ...}, sobre execuções success (§4.6)
    top_analyses: list[ExecutionTopAnalysis]
    top_users: list[ExecutionTopUser]
```

`ExecutionSummary` **não** inclui `error_message` (pode ser longo; fica no detalhe). Os enums de `status`/`error_code` dos filtros ficam em `schemas/admin.py`; a lista dos 7 códigos tem uma única fonte consultada por um teste que a compara com os `error_code` das exceções de `schemas/exceptions.py` (o contrato da F14 não pode divergir da API).

### 4.5 Listagem e detalhe

- **Ordenação:** `ORDER BY e.executed_at DESC, e.id DESC` (o desempate por `id` torna a paginação estável quando há `executed_at` iguais).
- **Consulta:** `execution_history e JOIN analyses a ON a.id = e.analysis_id LEFT JOIN users u ON u.id = e.user_id` (a FK de análise é NOT NULL; a de usuário é nula). A listagem inclui execuções de análises **inativas**.
- **Total:** `COUNT(*)` com os mesmos filtros (sem join desnecessário: o join com `analyses`/`users` não filtra nem multiplica linhas — só `LEFT JOIN`/chave primária — então a contagem usa apenas `execution_history e`). Filtro por `parameters` entra nos dois.
- **Filtro `parameters`:** o valor deve ser JSON válido **e um objeto** (`{...}`, não vazio), no máximo 1.000 caracteres; senão 422 `invalid_parameters_filter`. A contenção JSONB é sensível ao tipo (`{"ano":2025}` não casa com `"ano":"2025"`) porque `parameters` guarda o que o cliente MCP enviou. Documentado na resposta de erro e em §8.
- **Detalhe:** mesma consulta por `e.id`, 404 `execution_not_found` se não existe. `parameters` decodificado de `str` para `dict` (`_load_json`).
- **Atalho por análise:** o serviço confirma a análise com `AnalysisRepository.get_any_by_id` (inclui inativas; 404 `analysis_not_found` — `AdminAnalysisNotFoundError` da F24) e delega à mesma listagem com `analysis_id` fixo. Para `analysis_id`/`user_id` inexistentes em `GET /admin/executions` a resposta é uma página vazia (não 404): é um filtro, não um recurso.
- **Somente leitura:** sem `UPDATE`/`DELETE`/`INSERT`. Apagar/arquivar histórico é retenção, fora de escopo (§12 de NEGOCIO.md).

### 4.6 Estatísticas — `GET /admin/executions/stats`

Query: `from`, `to` (mesma semântica da §4.3), `analysis_id` e `user_id` opcionais (restringem o conjunto, úteis para "estatística desta análise" no frontend), `top` (1–20, padrão 5).

- **Período padrão:** sem `from` nem `to`, os **últimos 7 dias**; só `from` → até agora; só `to` → 7 dias antes de `to`. Os padrões são calculados **no SQL com `NOW()`** (mesmo relógio que grava `executed_at`, sem depender do fuso do processo Python) e o período efetivo volta em `period`.
- **Janela máxima:** `to − from` ≤ **366 dias**; acima disso → 422 `invalid_period` (protege o Config DB de varrer o histórico inteiro; constante no serviço, sem variável de ambiente nova).
- **Contagens:** `total`; `by_status` (os 4 status, zerados quando ausentes; um `status` fora desses não existe hoje e não é contado, só entraria no `total`); `by_error_code` (`GROUP BY error_code WHERE error_code IS NOT NULL`).
- **Cache:** `hits` = execuções `cached = true`; `success` = execuções `status = 'success'` (só elas podem ser servidas do cache — F7); `hit_rate = hits / success`, `null` quando `success = 0`. Erros e `volume_exceeded` ficam fora do denominador porque nunca são `cached`.
- **Tempo:** `avg`, `p95` (`percentile_cont(0.95) WITHIN GROUP (ORDER BY execution_time_ms)`) e `max`, calculados **separadamente** para `cache_hit` (`cached = true`) e `cache_miss` (`cached = false`), sobre execuções `status = 'success'` com `execution_time_ms` não nulo. Misturá-los esconderia a latência real das consultas ao banco atrás dos acertos de cache (milissegundos); a separação é a mesma das metas de RNF1 e do `scripts/benchmark.py` (F15). Cada grupo sem execuções devolve `avg`/`p95`/`max` nulos. Implementado com `FILTER (WHERE cached)` / `FILTER (WHERE NOT cached)` na agregação única.
- **Top N:** `top_analyses` (por nome da análise) e `top_users` (e-mail), ordenados por contagem desc, desempate por nome/id; execuções sem usuário (pré-F12) ficam fora de `top_users`, mas dentro do `total`.
- **Consultas:** uma agregação única com `FILTER (WHERE ...)` para total/status/cache/tempo + `GROUP BY` separado para `by_error_code`, `top_analyses` e `top_users` (4 consultas sequenciais, todas limitadas pelo `executed_at` do período — usam `idx_execution_history_executed_at`).

### 4.7 Erros e dados sensíveis

Formato `{"error": "<slug>", "message": "<texto em português>"}`, além dos slugs da F23/F24 (`unauthorized`, `forbidden`, `analysis_not_found`, `internal_error`):

| HTTP | `error` | Quando |
|---|---|---|
| 404 | `execution_not_found` | `GET /admin/executions/{id}` com id inexistente |
| 404 | `analysis_not_found` | atalho `/admin/analyses/{id}/executions` com análise inexistente (inativa é aceita) |
| 422 | `invalid_period` | `from >= to`, ou janela do `/stats` > 366 dias |
| 422 | `invalid_parameters_filter` | `parameters` não é JSON, não é objeto, é vazio ou passa de 1.000 caracteres |
| 422 | (padrão FastAPI) | UUID malformado, `status`/`error_code` fora do enum, `limit` fora de 1–200, `offset` < 0, `min_time_ms` < 0, datetime inválido, `top` fora de 1–20 |

(O slug `invalid_parameters_filter` é distinto de `INVALID_PARAMETERS` da F14, que pertence ao `/mcp`.)

**Dados sensíveis:**
- `parameters` e `error_message` são devolvidos **apenas a administradores** (a F25 existe para isso) e **nunca** são logados nem aparecem em mensagens de erro (nem o valor recebido em `?parameters=`).
- O texto de `error_message` é o que o servidor gravou na execução (F14: já sem credenciais de conexão). A API não faz mascaramento adicional (decisão 9).
- Nunca são devolvidos `users.password_hash`, tokens nem `connection_config` (a consulta seleciona colunas explícitas de `users`: `id`, `name`, `external_id`).

### 4.8 Banco de Dados

**Sem DDL novo, sem `ALTER`, sem índice novo na implementação inicial.** Consultas parametrizadas (`$n`, nunca interpolação de valores; o `WHERE` é montado só com fragmentos fixos do código):

```sql
-- listagem (filtros opcionais $1–$9; $10 = limit, $11 = offset)
SELECT e.id, e.analysis_id, a.name AS analysis_name,
       e.user_id, u.name AS user_name, u.external_id AS user_email,
       e.status, e.error_code, e.cached, e.parameters,
       e.execution_time_ms, e.rows_affected, e.result_size_bytes, e.executed_at
  FROM execution_history e
  JOIN analyses a ON a.id = e.analysis_id
  LEFT JOIN users u ON u.id = e.user_id
 WHERE ($1::uuid IS NULL OR e.analysis_id = $1)
   AND ($2::uuid IS NULL OR e.user_id = $2)
   AND ($3::text IS NULL OR e.status = $3)
   AND ($4::text IS NULL OR e.error_code = $4)
   AND ($5::boolean IS NULL OR e.cached = $5)
   AND ($6::timestamp IS NULL OR e.executed_at >= $6)
   AND ($7::timestamp IS NULL OR e.executed_at <  $7)
   AND ($8::int IS NULL OR e.execution_time_ms >= $8)
   AND ($9::jsonb IS NULL OR e.parameters @> $9::jsonb)
 ORDER BY e.executed_at DESC, e.id DESC
 LIMIT $10 OFFSET $11;
```

(`execute_query` liga o dict por posição: o dict de filtros mantém a ordem dos `$n`, como em `analysis_repo.admin_list`. Os parâmetros opcionais têm cast explícito porque o Postgres não infere o tipo de `$n IS NULL`.)

**Índices:** os atuais (`analysis_id`, `executed_at`, `user_id`) bastam para os filtros isolados. Candidatos, **criados só se o `EXPLAIN` justificar** (mesmo critério da F15; DATABASE_SCHEMA.md §8) e como `CREATE INDEX` manual documentado — nunca em `schema.sql` sem evidência:
- `(analysis_id, executed_at DESC)` — "histórico de uma análise" ordenado;
- `(executed_at DESC, id DESC)` — a ordenação padrão com paginação profunda;
- GIN em `parameters` — só se a contenção `@>` ficar lenta sobre o conjunto já filtrado por análise/período.

**Procedimento de medição (§6.2):** popular um Config DB descartável com volume sintético (`generate_series`, ex.: 1 M de linhas com distribuição realista de análises/usuários/status), rodar `EXPLAIN (ANALYZE, BUFFERS)` das consultas da listagem (sem filtro, por análise, por usuário+período, por `parameters`), do `COUNT(*)` e do `/stats` (janela de 7 e de 366 dias) e registrar na §12. Se alguma ultrapassar uma meta razoável (p95 da listagem < 200 ms; `/stats` de 7 dias < 1 s), propor o índice (decisão a confirmar) antes de criá-lo.

### 4.9 Interfaces (assinaturas)

```python
# repositories/execution_repo.py  (create() inalterado; get_all() removido)
@dataclass
class ExecutionFilters:
    analysis_id: UUID | None = None
    user_id: UUID | None = None
    status: str | None = None
    error_code: str | None = None
    cached: bool | None = None
    executed_from: datetime | None = None      # naive
    executed_to: datetime | None = None        # naive, exclusivo
    min_time_ms: int | None = None
    parameters: dict | None = None             # contenção JSONB

class ExecutionRepository:
    async def search(self, filters: ExecutionFilters, limit: int, offset: int) -> list[dict]
    async def count(self, filters: ExecutionFilters) -> int
    async def get_detail(self, execution_id: UUID) -> dict | None      # + error_message
    async def stats(self, executed_from, executed_to, analysis_id, user_id, top: int) -> dict

# services/execution_admin_service.py
class ExecutionAdminService:
    def __init__(self, repo: ExecutionRepository, analyses: AnalysisRepository) -> None
    async def list_executions(self, filters: ExecutionFilters, limit: int, offset: int) -> Page[ExecutionSummary]
    async def list_by_analysis(self, analysis_id: UUID, filters, limit, offset) -> Page[ExecutionSummary]
    async def get_execution(self, execution_id: UUID) -> ExecutionDetail
    async def get_stats(self, executed_from, executed_to, analysis_id, user_id, top: int) -> ExecutionStats
```

Exceções (herdam de `AdminError`, em `schemas/admin.py`): `ExecutionNotFoundError` (404 `execution_not_found`), `InvalidPeriodError` (422 `invalid_period`), `InvalidParametersFilterError` (422 `invalid_parameters_filter`).

---

## 5. Critérios de Aceitação

```gherkin
Feature: API administrativa — histórico de execuções

Scenario: Controle de acesso
  When Chamo qualquer rota nova sem token / com token de não-admin
  Then Recebo 401 unauthorized / 403 forbidden (varredura de todas as rotas /admin/*)

Scenario: Listar com filtros e paginação
  Given Execuções de várias análises, usuários, status e datas
  When GET /admin/executions?analysis_id=A&status=error&from=...&to=...&limit=10&offset=0
  Then Recebo {items,total,limit,offset} só com as que casam, da mais recente para a mais antiga
  And Cada item traz analysis{id,name}, user{id,name,email}, parameters, tempo, linhas e bytes
  And Sem nenhum filtro recebo todas, paginadas (limit padrão 50, máximo 200)

Scenario: Execução pré-F12 e análise inativa
  Given Uma execução com user_id NULL e outra de uma análise inativa
  When Listo o histórico
  Then A primeira vem com "user": null e ambas aparecem

Scenario: Filtros combinados
  When Filtro por error_code=QUERY_TIMEOUT, por cached=true, por min_time_ms=1000 e por user_id
  Then Cada filtro restringe corretamente e combina com AND

Scenario: Filtro por parâmetro
  Given Execuções com parameters {"regiao":"SP","ano":2025} e {"regiao":"RJ"}
  When GET /admin/executions?parameters={"regiao":"SP"}
  Then Só a primeira volta
  When parameters não é JSON, é um array, um objeto vazio ou passa de 1000 caracteres
  Then 422 invalid_parameters_filter e nada é consultado

Scenario: Enum e período inválidos
  When status="failed", error_code="X", limit=0 ou UUID malformado
  Then 422 (padrão FastAPI)
  When from >= to
  Then 422 invalid_period

Scenario: Detalhe
  When GET /admin/executions/{id} de uma execução com status error
  Then Recebo o detalhe com error_message e error_code
  When O id não existe
  Then 404 execution_not_found

Scenario: Atalho por análise
  When GET /admin/analyses/{id}/executions (com e sem filtros)
  Then Recebo só as execuções dessa análise, paginadas
  When A análise não existe
  Then 404 analysis_not_found
  And Uma análise inativa é aceita

Scenario: Estatísticas do período
  Given Execuções success (algumas cached), error, timeout e volume_exceeded no período
  When GET /admin/executions/stats?from=...&to=...
  Then Recebo total, by_status (os 4 status), by_error_code, cache.hit_rate, avg/p95/max do tempo separados em cache_hit e cache_miss
       e top_analyses/top_users limitados por top
  And Sem execuções o resultado é zerado e hit_rate/p95 são null
  When Não informo from/to
  Then Vale os últimos 7 dias e o período efetivo vem em "period"
  When A janela passa de 366 dias
  Then 422 invalid_period

Scenario: Somente leitura
  Then Nenhuma rota nova altera execution_history nem qualquer tabela

Scenario: Dados sensíveis
  Then parameters, error_message e o filtro "parameters" recebido não aparecem em log
  And password_hash, tokens e connection_config nunca são devolvidos

Scenario: /mcp inalterado
  Then Gravar execuções pelo /mcp (AuditService.create) continua igual
```

---

## 6. Testes

### 6.1 Testes Unitários / de Rota

Padrão da F23/F24 (`tests/test_admin_api.py`, `tests/admin_fakes.py`): FastAPI mínimo com `include_router` + `dependency_overrides`, repositório fake em memória (`FakeExecutionRepository` em `admin_fakes.py` implementando `search`/`count`/`get_detail`/`stats` sobre uma lista de dicts), sem lifespan nem banco.

```python
class TestSweepAuthorization:       # a varredura de /admin/* passa a incluir as rotas novas (401/403)
class TestListExecutions:           # sem filtro; cada filtro isolado e combinado; ordenação desc + desempate;
                                    # paginação (limit/offset/total); user null; análise inativa; parameters como dict
class TestParametersFilter:         # objeto válido; JSON inválido, array, {}, > 1000 chars -> 422 invalid_parameters_filter;
                                    # tipo sensível (2025 vs "2025")
class TestFilterValidation:         # status/error_code fora do enum, UUID malformado, limit/offset/min_time_ms/top inválidos (422);
                                    # from >= to -> invalid_period; enum de error_code == códigos de schemas/exceptions.py
class TestExecutionDetail:          # 200 com error_message; 404 execution_not_found; result_location ausente
class TestAnalysisShortcut:         # filtra pela análise; 404 inexistente; inativa aceita; aceita os demais filtros
class TestStats:                    # contagens por status (4 chaves zeradas) e error_code; hit_rate = hits/success e null sem success;
                                    # avg/p95/max só de success, separados em cache_hit/cache_miss (grupo vazio -> nulos); top N e ordem; período padrão 7 dias; só from / só to;
                                    # janela > 366 dias -> invalid_period; filtros analysis_id/user_id
class TestReadOnly:                 # nenhuma chamada de escrita no repositório/adapter durante as rotas novas
class TestNoSensitiveInLogs:        # caplog: sem parameters, error_message nem o filtro recebido
```

`tests/test_execution_repo.py` é adaptado: `get_all` sai; entram testes de `search`/`count`/`get_detail`/`stats` sobre um adapter fake que captura SQL e valores (ordem dos `$n`, casts, `LIMIT/OFFSET`, `@>` só quando há filtro).

### 6.2 Integração (Config DB real)

Arquivo no padrão de `tests/test_admin_data_sources_analyses_integration.py` (pula sozinho sem banco ou sem `users.is_admin`/`execution_history.error_code`): inserir execuções reais (via `ExecutionRepository.create`, o mesmo caminho do `/mcp`) e conferir: `parameters` JSONB lido de volta como dict; filtro `@>` real (objeto, tipos); `LEFT JOIN` com `user_id` nulo; ordenação/paginação estável com `executed_at` iguais; `from` inclusivo / `to` exclusivo; `percentile_cont` e `FILTER` do `/stats` com valores conhecidos (p95 exato de um conjunto pequeno, hit e miss separados); **`SHOW timezone` do Config DB = UTC** (protege a premissa do fuso, decisão 11); **ciclo completo**: executar uma análise pelo `AnalysisService` (sucesso, cache hit, erro) e vê-las em `/admin/executions` e `/stats`; limpeza das linhas criadas.

**Medição de índices (não é teste automatizado):** procedimento da §4.8 sobre volume sintético em banco descartável; resultado e decisão sobre índices registrados na §12.

### 6.3 Checklist de Testes
- [x] 401/403 em todas as rotas novas (varredura)
- [x] Cada filtro (isolado e combinado), ordenação e paginação da listagem
- [x] Filtro `parameters` (válido e as 4 recusas) e sensibilidade a tipo
- [x] Execuções com `user_id` NULL e de análise inativa aparecem
- [x] Detalhe (com `error_message`) e 404
- [x] Atalho por análise (incl. 404 e inativa)
- [x] `/stats`: status zerados, `by_error_code`, `hit_rate`, avg/p95/max por cache_hit/cache_miss, top N, período padrão, janela máxima
- [x] `from` inclusivo / `to` exclusivo; `from >= to` → `invalid_period`
- [x] Somente leitura; nada sensível em log
- [x] Os 7 códigos do filtro coincidem com os de `schemas/exceptions.py`
- [x] `get_all`/`get_execution_history` removidos sem quebrar nada (regressão do `AuditService` e do `/mcp`)
- [x] Integração com Postgres real (JSONB, `@>`, joins, percentil, ciclo executar → consultar)
- [x] `EXPLAIN` em volume sintético registrado (§12) e decisão sobre índices
- [x] Suíte completa (672+) passando com `.venv`
- [ ] Manual: com o compose local, executar análises por um cliente MCP real (sucesso, cache hit, erro) e consultá-las por `/admin/executions` e `/stats` com o token do admin

---

## 7. Mudanças na Configuração

Sem variáveis novas no `.env` (janela máxima de 366 dias, período padrão de 7 dias, limite de 1.000 caracteres do filtro e `top` máximo 20 são constantes no serviço). Sem nova dependência. **Sem `ALTER TABLE`/DDL** — `execution_history.error_code` (F14) e `users.is_admin` (F23) já são pré-requisitos existentes. Eventuais índices (§4.8) só como `CREATE INDEX` manual documentado, se a medição justificar.

## 8. Documentação

### 8.1 Como a feature aparece no MCP
Não aparece: é API HTTP separada do `/mcp`, somente leitura. O `/mcp` segue gravando o histórico exatamente como antes (F8/F12/F14).

### 8.2 Como o usuário usa
O frontend (fora de escopo) autentica como administrador (`POST /auth/token`) e usa `Authorization: Bearer`. Fluxos típicos:
```
GET /admin/executions?status=error&from=2026-10-08T00:00:00          # o que falhou hoje
GET /admin/executions?user_id=<uuid>&limit=20                         # o que o usuário executou
GET /admin/executions?error_code=QUERY_TIMEOUT&min_time_ms=5000       # timeouts lentos
GET /admin/analyses/<uuid>/executions?parameters={"regiao":"SP"}      # chamadas de uma análise com um parâmetro
GET /admin/executions/<uuid>                                          # detalhe + error_message
GET /admin/executions/stats?from=2026-10-01&to=2026-10-08&top=10      # painel do período
```
Notas para o frontend: `from` é inclusivo e `to` exclusivo; datas sem fuso são comparadas como estão gravadas (UTC no compose); `parameters` mostra o que o cliente MCP enviou (sem defaults resolvidos) e o filtro `parameters` casa valores **com o mesmo tipo JSON**.

### 8.3 Como outros desenvolvedores estenderão
Novo filtro = um campo em `ExecutionFilters`, um fragmento no `WHERE` (na ordem do dict de filtros) e um parâmetro de `Query` nas duas rotas. Retenção/purge do histórico e exportação (CSV) ficam como evolução futura; se a tabela crescer, a decisão de índices/particionamento parte do `EXPLAIN` da §4.8.

---

## 9. Checklist de Implementação

**Código:**
- [x] `ExecutionFilters`, `search`/`count`/`get_detail`/`stats` em `execution_repo.py` (remoção de `get_all` e de `AuditService.get_execution_history`)
- [x] Modelos e 3 exceções em `schemas/admin.py`
- [x] `services/execution_admin_service.py`
- [x] `routes/admin_executions.py`, atalho em `routes/admin_analyses.py`, `routes/dependencies.py`, `main.py`
- [x] Docstrings

**Documentação (ao concluir):**
- [x] Preencher §12; marcar F25 como 🟩 no ROADMAP e no `.claude/CLAUDE.md`
- [x] ARQUITETURA.md §2.4 (F25 ✅, nome do arquivo `admin_executions.py` e remoção de `get_all` confirmados) e DATABASE_SCHEMA.md §2.5/§8 (decisão sobre índices)

**QA:**
- [x] Suíte completa passando (com `.venv`)
- [x] `EXPLAIN` em volume sintético registrado
- [ ] Validação manual (§6.3)
- [ ] Code review

---

## 10. Decisões

| # | Decisão | Origem |
|---|---|---|
| 1 | API somente leitura; sem `admin_action`, sem tabela de auditoria, sem retenção/purge | NEGOCIO.md §12 / ARQUITETURA.md §2.4 |
| 2 | Paginação obrigatória (`limit` padrão 50, máx. 200), ordenação `executed_at DESC, id DESC` | ARQUITETURA.md §2.4 / F23 decisão 14 |
| 3 | `ExecutionRepository.get_all` é substituído por `search` + `count` (e `AuditService.get_execution_history`, sem chamador, é removido) | ARQUITETURA.md §2.4 |
| 4 | Filtros: `analysis_id`, `user_id`, `status`, `error_code`, `cached`, `from`/`to`, `min_time_ms`, mais `parameters` (contenção JSONB) | ARQUITETURA.md §2.4 |
| 5 | Índices só se o `EXPLAIN` justificar (mesmo critério da F15); nenhum na entrega inicial | ARQUITETURA.md §2.4 / DATABASE_SCHEMA.md §8 |
| 6 | Erros no slug `{"error","message"}`; 422 de validação no formato padrão do FastAPI | ADR-008 / F23 decisão 15 |
| 7 | `GET /admin/analyses/{id}/executions` vive no router de analyses e reaproveita o serviço de execuções | F24 §3 |
| 8 | `parameters @>` nas duas rotas (listagem e atalho), como JSON objeto não vazio ≤ 1.000 caracteres, tipo exato; sem GIN até o `EXPLAIN` justificar | Confirmada 2026-10-08 (P1) |
| 9 | `parameters` e `error_message` devolvidos integralmente, só a administrador, nunca em log; sem mascaramento | Confirmada 2026-10-08 (P5) |
| 10 | Tempo do `/stats` separado em `cache_hit` × `cache_miss` (alinhado a RNF1/F15); `/stats` com padrão de 7 dias, janela máxima de 366 dias e `top` 1–20 (padrão 5), constantes no serviço | Confirmada 2026-10-08 (P2, P3) |
| 11 | Fuso: `from`/`to` naive comparados como gravados, com offset → UTC; teste de integração falha se o Config DB não estiver em UTC | Confirmada 2026-10-08 (P4) |
| 12 | `ExecutionRepository.get_all` e `AuditService.get_execution_history` removidos; `tests/test_execution_repo.py` adaptado | Confirmada 2026-10-08 (P6) |

## 11. Pontos em aberto

Nenhum. Os 6 pontos propostos na escrita da spec foram confirmados pelo responsável em 2026-10-08 (a P2 foi alterada em relação à proposta original; as demais seguiram o padrão proposto) e estão na §10 (decisões 8 a 12):

| # | Ponto | Resolução |
|---|---|---|
| ~~P1~~ | Filtro `parameters @>` | ✅ Nas duas rotas, JSON objeto, tipo exato (decisão 8) |
| ~~P2~~ | Tempo no `/stats` | ✅ Separado em `cache_hit` × `cache_miss` (decisão 10) — **mudou** em relação à proposta (misturado) |
| ~~P3~~ | Limites do `/stats` | ✅ 7 dias / 366 dias / `top` 1–20 (decisão 10) |
| ~~P4~~ | Fuso de `from`/`to` | ✅ Naive como gravado; offset → UTC; teste de `SHOW timezone` (decisão 11) |
| ~~P5~~ | Exposição de `parameters`/`error_message` | ✅ Integral, só admin, nunca em log (decisão 9) |
| ~~P6~~ | Remover `get_all` / `get_execution_history` | ✅ Remover (decisão 12) |

## 12. Implementação

**Resultado (2026-10-08):** 735/735 testes ✅ com `.venv` (672 anteriores + 50 de rota/serviço em `tests/test_admin_executions.py` com `FakeExecutionRepo` em `tests/admin_fakes.py` + 7 de integração em `tests/test_admin_executions_integration.py` contra o Postgres do compose + 6 novos de SQL em `tests/test_execution_repo.py`, que trocou o teste de `get_all`; 1 skip pré-existente).

**Arquivos novos:** `services/execution_admin_service.py` (`build_filters`, `parse_parameters_filter`, `ExecutionAdminService`), `routes/admin_executions.py`. **Modificados:** `repositories/execution_repo.py` (`ExecutionFilters`, `search`/`count`/`get_detail`/`resolve_period`/`stats`; `get_all` removido), `services/audit_service.py` (`get_execution_history` removido), `schemas/admin.py` (modelos `Execution*`, `ExecutionStatus`/`ExecutionErrorCode`, 3 exceções), `routes/admin_analyses.py` (atalho `/{id}/executions`), `routes/dependencies.py`, `main.py`. Sem DDL, sem `.env` novo, sem dependência nova.

**Desvios em relação ao desenho:**
- `resolve_period` é um método próprio do repositório (uma consulta com `LOCALTIMESTAMP`), chamado antes de `stats`: o período efetivo precisa existir para validar a janela de 366 dias e voltar em `period`. Logo o `/stats` faz 5 consultas (1 de período + 4 de agregados), não 4.
- Os filtros viram dependência FastAPI: `analysis_execution_filters` (sem `analysis_id`) é compartilhada pela listagem e pelo atalho; `execution_filters` acrescenta `analysis_id`.
- O `/stats` expõe também `count` em cada `TimeStats` (execuções que entraram no cálculo); `from` no futuro (ou qualquer período efetivo invertido) → 422 `invalid_period`.
- O teste de log filtra o logger `httpx` (o cliente de teste loga a URL com o `?parameters=`; não é log da aplicação).

**`EXPLAIN` em volume sintético (decisão 5, §4.8):** schema descartável `f25_bench` (já removido) com 1 M de execuções (50 análises, 200 usuários, 400 dias, tabela de 178 MB), `EXPLAIN (ANALYZE, BUFFERS)` e tempo mínimo de 3 execuções:

| Consulta | Só índices atuais | + `(analysis_id, executed_at DESC)` | + GIN `parameters` |
|---|---|---|---|
| lista sem filtro (página 1) | 0,6 ms | — | — |
| lista por análise / por usuário+7 d / `status=error`+30 d | 1,3 / 2,3 / 1,0 ms | 0,7 ms (por análise) | — |
| lista `offset=100000` | 188 ms | — | — |
| lista `parameters @>` sem outros filtros (raro ou médio) | 57–62 ms | 56–58 ms | 2–6 ms |
| lista análise + `@>` (casa) | 4,4 ms | 0,9 ms | 0,9 ms |
| **lista análise + `@>` que não casa nenhuma linha da análise** | **1.530 ms** | **43 ms** | 52 ms |
| `COUNT` sem filtro / por análise / `@>` | 31 / 52 / 60 ms | — | `@>`: 6 ms |
| `/stats` agregado 7 d / 366 d | 15 / 386 ms | — | — |

Conclusão: tudo cumpre a meta (listagem < 200 ms, `/stats` de 7 dias < 1 s) **exceto** um caso — filtrar uma análise por um `parameters` que quase não ocorre: o planejador percorre o índice de `executed_at` (esperando achar 50 linhas) e varre quase a tabela (**1,5 s**). O índice composto `(analysis_id, executed_at DESC)` o reduz a 43 ms (39 MB com 1 M de linhas). O GIN só melhora casos que já estão em ~60 ms (e a busca por `parameters` sem análise, que é o caso de uso mais raro): **não justificado**. Offset de 100 mil é paginação profunda irreal para um painel. **Decisão pendente do responsável:** criar o índice composto (manual, não vai ao `schema.sql` antes de confirmado):
```sql
CREATE INDEX idx_execution_history_analysis_executed_at ON execution_history (analysis_id, executed_at DESC);
```

**Como rodar:** `.venv/bin/python -m pytest tests` (a integração usa o Config DB do `.env`, `localhost:5433`, e pula sozinha sem banco; exige o Config DB em UTC — `SHOW timezone`).
