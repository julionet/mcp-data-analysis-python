# [F14] Error Handling & Validation

## Feature Spec

**ID:** F14
**Nome:** Error Handling & Validation — erros com código estável, timeout distinto, retry e contrato "nunca propaga exceção" fechado
**Prioridade:** 🟠 Alta
**Esforço Estimado:** 1d (8h)
**Status:** 🟩 Done (2026-10-03) — 480/480 testes ✅; validação manual pendente (§6.2): queda do Config DB com cliente real, timeout de query em PostgreSQL e SQL Server, `ALTER TABLE` no banco existente

> **Origem dos requisitos:** FEATURES_ROADMAP.md (linha da F14 e bloco "F14 em detalhe", adicionado junto com esta spec), NEGOCIO.md RNF4 (Confiabilidade: isolation de erro e retry 3x com backoff) e RNF5 (validação de todos os inputs), ARQUITETURA.md §8.1 (timeout de query) e as pendências das specs F11 (§10) e F12 (§10). Decisões desta sessão registradas na §10.

---

## 1. Visão

Hoje o servidor devolve o erro como texto livre em `mensagem`: o LLM do cliente MCP não consegue distinguir um parâmetro inválido (que ele corrige e reenvia) de um banco fora do ar (que ele não corrige), nem um timeout (que pede um filtro mais estreito). Além disso, parte do caminho de `call_tool()`/`list_tools()` ainda pode vazar exceção para o transporte MCP.

A F14 dá a todo erro um `error_code` estável e um `retryable`, grava o timeout como status próprio no histórico, repete automaticamente só o que é transitório e fecha as brechas do contrato "nunca propaga exceção".

## 2. Objetivo

Padronizar o tratamento de erro ponta a ponta, **sem mudar** o contrato dos status `success` e `volume_exceeded` e sem trocar o dict por `isError` do protocolo MCP (contrato da F5 preservado).

**Métrica de Sucesso:**
- ✅ Todo retorno `{"status": "error"}` carrega `error_code` (valor de um conjunto fechado, §4.2) e `retryable` (bool)
- ✅ Timeout de query devolve `QUERY_TIMEOUT` e grava `execution_history.status = 'timeout'`
- ✅ Falha de conexão ao data source é repetida até 3 vezes com backoff exponencial; erro de SQL e de validação nunca são repetidos
- ✅ Queda do Config DB durante `call_tool()`/`list_tools()` não vaza exceção: `call_tool()` devolve o dict estruturado e `list_tools()` devolve erro tratado e logado
- ✅ `confirmar_volume_alto` só é aceito como booleano de verdade (uma string `"false"` não pode virar bypass do Volume Guard)
- ✅ Testes existentes de F5/F7/F8/F12 continuam passando (campos novos são aditivos)

## 3. Contexto

**Depende de:** F4 (Execution Engine), F5 (MCP Tools), F8 (Log de Execução), F12 (Autenticação) — todas ✅.
**É dependência de:** F15 (Performance Optimization), F17 (Unit Tests), F18 (Integration Tests), F16 (API Documentation — documenta o contrato de erro).

## 4. Descrição Técnica

### 4.1 Componentes Afetados

```
├─ schemas/exceptions.py              (modificado) error_code/retryable por exceção; novas QueryTimeoutError, QueryExecutionError
├─ services/analysis_service.py       (modificado) resposta de erro com error_code/retryable; status 'timeout'; retry no connect e na query
├─ services/retry.py                  (novo)       retry_async() com backoff exponencial
├─ services/audit_service.py          (modificado) aceita status 'timeout'; grava error_message também nele
├─ adapters/base.py                   (modificado) is_timeout_error()/is_transient_error() — default False
├─ adapters/postgresql.py|mysql.py|oracle.py|sqlserver.py (modificados) classificam as exceções do próprio driver
├─ mcp_transport/tools.py             (modificado) try em list_tools()/call_tool(); validação de arguments e de confirmar_volume_alto
├─ main.py                            (modificado) exception_handler(Exception) — cobre /auth/* e /health (não o /mcp, ver 4.4)
├─ config.py                          (modificado) QUERY_RETRY_MAX_ATTEMPTS, QUERY_RETRY_BACKOFF_BASE_MS
├─ database/schema.sql                (comentário)  valores reais de execution_history.status — sem DDL
└─ .env.example                       (modificado) variáveis novas
```

### 4.2 Contrato de erro

Resposta de erro (campos novos em **negrito**; `status`, `mensagem` e `cached` continuam como hoje):

```python
{"status": "error", "error_code": "QUERY_TIMEOUT", "retryable": True,
 "mensagem": "A consulta excedeu o tempo limite (30s). Refine o período ou adicione filtros.", "cached": False}
```

| Exceção | `error_code` | `retryable` (para o cliente) | Status em `execution_history` | Retry automático no servidor |
|---|---|---|---|---|
| `AnalysisNotFoundError` **e** acesso negado em `call_tool()` (decisão 6) | `ANALYSIS_NOT_FOUND` — mesma resposta e mesma mensagem nos dois casos | false | — (não há `analysis_id` válido / hoje só log; ver §10) | não |
| `InvalidParametersError` (inclui `confirmar_volume_alto` não booleano) | `INVALID_PARAMETERS` | false (corrigir e reenviar) | `error` | não |
| `InvalidAnalysisSchemaError`, `InvalidCacheFrequencyError` | `INVALID_ANALYSIS_CONFIG` | false (erro de cadastro, não do cliente) | `error` | não |
| `DataSourceConnectionError` (conexão/pool indisponível) | `DATA_SOURCE_UNAVAILABLE` | true | `error` | **sim**, até `QUERY_RETRY_MAX_ATTEMPTS` |
| `QueryTimeoutError` (novo, subclasse de `DataSourceConnectionError`) | `QUERY_TIMEOUT` | true (com filtro mais estreito) | **`timeout`** | não (ver §11, item 3) |
| `QueryExecutionError` (novo, subclasse de `DataSourceConnectionError`; erro de SQL) | `QUERY_FAILED` | false | `error` | não |
| qualquer outra `Exception` | `INTERNAL_ERROR` | false | `error` | não |

`volume_exceeded` não muda: não é erro, não ganha `error_code`. As subclasses mantêm `DataSourceConnectionError` como base para que os `except` atuais de `AnalysisService` continuem válidos; renomear a base fica fora do escopo.

A tradução exceção → (`error_code`, `retryable`) vive como atributos de classe em `schemas/exceptions.py`; `AnalysisService.execute()` monta o dict a partir deles, sem `if/elif` por tipo.

### 4.3 Fluxo de Dados

```
call_tool(name, arguments, user)
 ├─ arguments não-dict → INVALID_PARAMETERS
 ├─ confirmar_volume_alto presente e não-bool → INVALID_PARAMETERS
 ├─ get_by_name / is_analysis_allowed       ← agora dentro de try: falha de Config DB → INTERNAL_ERROR (logado)
 └─ analysis_service.execute()
      ├─ valida parâmetros (Pydantic)        → INVALID_PARAMETERS
      └─ _run_query()
           ├─ _get_adapter()   ── retry_async (só falha de conexão) → DATA_SOURCE_UNAVAILABLE
           ├─ Volume Guard (COUNT) ── mesmo retry_async da query (decisão 7)
           └─ adapter.execute_query()
                ├─ adapter.is_timeout_error(exc)   → QueryTimeoutError  → status 'timeout' (sem retry, decisão 8)
                ├─ adapter.is_transient_error(exc) → retry_async; esgotado → DATA_SOURCE_UNAVAILABLE
                └─ demais                          → QueryExecutionError (QUERY_FAILED)

Acesso negado: call_tool() devolve ANALYSIS_NOT_FOUND com o MESMO texto de "não existe"
("Análise '<nome>' não encontrada ou inativa."); a diferença só aparece no log
(`access_denied user_id=... analysis_id=...`, já existente da F12).
```

**Retry (conexão, `COUNT(*)` e query):** a pré-checagem do Volume Guard e a query principal são cada uma envolvidas por `retry_async`. `VolumeExceededError` não é transitório, então nunca é repetida. `retry_async(fn, attempts, base_ms, is_retryable)` — espera `base_ms * 2^(n-1)` entre tentativas (200 ms, 400 ms com os padrões), loga um `warning` por tentativa (`análise`, `data_source`, `tentativa n/N`) e relança a última exceção. Só é seguro porque `validate_select_only()` garante que a query é um SELECT (idempotente); o retry nunca se aplica a `adapter.execute()` (DML).

**Classificação por adapter (implementada no passo 2, verificada contra os drivers instalados):** o `AnalysisService` não conhece os drivers. Cada adapter implementa `is_timeout_error(exc)` (estouro do timeout de **query**) e `is_transient_error(exc)` (falha **rápida** de conexão; nunca timeout):

| Adapter | `is_timeout_error` | `is_transient_error` |
|---|---|---|
| PostgreSQL (asyncpg) | `TimeoutError` (`command_timeout`), `QueryCanceledError` (57014) | `ConnectionError`, `PostgresConnectionError` (08xxx), `CannotConnectNowError`, `TooManyConnectionsError`, `AdminShutdownError`, `CrashShutdownError` |
| MySQL (aiomysql) | `OperationalError` 3024 | `ConnectionError`; `OperationalError` 2003 (exceto "timed out"), 2006, 2013, 2055, 1040, 1053 |
| SQL Server (pyodbc) | SQLSTATE `HYT00` com "query" na mensagem | `ConnectionError`; SQLSTATE `08xxx`, `01002` (`HYT00` de login e `HYT01` ficam de fora) |
| Oracle (oracledb) | `args[0].full_code` ∈ {`DPY-4024`, `ORA-03156`} | `ConnectionError`; `full_code` ∈ {`DPY-4011`, `ORA-03113`, `ORA-03114`, `ORA-12541`, `ORA-01033`, `ORA-01089`} — `DPY-6005` fora (genérico demais); **sem validação em instância Oracle** | A base devolve `False`, então um adapter novo sem override simplesmente não ganha retry nem `timeout`.

### 4.4 Contrato "nunca propaga exceção" — onde fica cada proteção

- **`call_tool()`** (`mcp_transport/tools.py`): `get_by_name` e `is_analysis_allowed` ficam dentro de um `try`; qualquer exceção vira `{"status": "error", "error_code": "INTERNAL_ERROR", ...}` e é logada com `logger.exception`.
- **`list_tools()`**: em falha loga (`logger.exception`) e levanta `McpError(ErrorData(code=-32603, message="Erro interno ao listar as análises."))` — o SDK devolve o erro JSON-RPC com essa mensagem genérica.
- **`main.py`**: `@app.exception_handler(Exception)` devolve 500 JSON genérico (`{"error": "internal_error", "message": "Erro interno do servidor."}`) para qualquer exceção que escape — na prática `/auth/*` e `/health`. No `/mcp` ele só pegaria o que escapasse do SDK; a proteção real do `/mcp` é a do `tools.py` acima.

**Comportamento do SDK `mcp` 1.30.0 (conferido no código instalado — fecha o §11, item 4):**
- `call_tool`: qualquer exceção do handler vira `CallToolResult(isError=True)` com **`str(exc)` como texto** — vazaria host/SQL do driver ao cliente. Por isso `tools.call_tool()` captura tudo antes e devolve o dict com mensagem genérica.
- `list_tools`: o SDK **não captura**; a exceção chega ao `_handle_request`, que responde erro JSON-RPC com `code=0` e `str(err)`. Daí o `McpError` com código e mensagem controlados.
- Validação de entrada: o SDK valida os `arguments` contra o `inputSchema` **só se a tool estiver no cache dele** (a lista do último `list_tools`); para uma tool que o usuário não vê, loga "not listed, no validation will be performed" e segue. Por isso a validação de `confirmar_volume_alto` e de `arguments` fica em `tools.py`, e não se confia no SDK.

### 4.5 Banco de Dados

`execution_history.status` é `VARCHAR(50)` e passa a receber também `timeout` (sem DDL). O comentário do `schema.sql` (`success, failed, timeout`) citava `failed`, valor que o código nunca gravou — corrigido para `success, volume_exceeded, error, timeout`.

**Coluna nova (decisão 12):** `error_code VARCHAR(50)`, nullable, gravada só para `error`/`timeout` — o mesmo código devolvido ao cliente, para permitir agrupar erros por tipo na auditoria. Sem migration (padrão do projeto, como o `user_id` da F12): o `schema.sql` cria a coluna em bancos novos; em bancos existentes, executar uma vez, direto no banco:

```sql
ALTER TABLE execution_history ADD COLUMN error_code VARCHAR(50);
```

**Risco se esquecer o `ALTER`:** o `INSERT` do `ExecutionRepository` passa a falhar e o `AuditService` só loga o erro — o histórico para de ser gravado sem derrubar as respostas (fere RNF4, "100% das execuções registradas"). Um teste (`test_insert_columns_match_schema_sql`) garante que o `INSERT` e o `schema.sql` falam das mesmas colunas.

### 4.6 Interfaces

```python
# services/retry.py
async def retry_async(fn, *, attempts: int, base_ms: int, is_retryable) -> Any: ...

# adapters/base.py (não abstratos — default False)
def is_timeout_error(self, exc: Exception) -> bool: return False
def is_transient_error(self, exc: Exception) -> bool: return False
```

## 5. Critérios de Aceitação

```gherkin
Feature: Error Handling & Validation

Scenario: Parâmetro inválido
  Given uma análise com parâmetro `data_inicial` do tipo date
  When o cliente envia data_inicial = "abc"
  Then retorna {"status":"error","error_code":"INVALID_PARAMETERS","retryable":false,...}
  And execution_history grava status 'error'

Scenario: confirmar_volume_alto não booleano
  When o cliente envia confirmar_volume_alto = "false"
  Then retorna INVALID_PARAMETERS e o Volume Guard NÃO é contornado

Scenario: Timeout de query
  Given o data source excede QUERY_TIMEOUT_SECONDS
  When a análise é executada
  Then retorna {"status":"error","error_code":"QUERY_TIMEOUT","retryable":true,...}
  And execution_history grava status 'timeout' com error_message
  And não há retry automático

Scenario: Falha transitória de conexão
  Given o data source recusa a conexão nas 2 primeiras tentativas e aceita na 3ª
  When a análise é executada
  Then retorna success
  And foram feitas 3 tentativas com espera de 200 ms e 400 ms

Scenario: Data source fora do ar
  Given a conexão falha em todas as QUERY_RETRY_MAX_ATTEMPTS tentativas
  Then retorna DATA_SOURCE_UNAVAILABLE com retryable true
  And a mensagem não expõe host, usuário nem stack trace

Scenario: Erro de SQL
  Given o banco rejeita o SQL da análise
  Then retorna QUERY_FAILED com retryable false
  And o adapter é chamado uma única vez (sem retry)

Scenario: Falha transitória no COUNT(*) do Volume Guard
  Given o COUNT(*) falha por conexão na 1ª tentativa e funciona na 2ª
  Then a análise segue normalmente (success ou volume_exceeded)
  And volume_exceeded NÃO dispara retry

Scenario: Usuário sem permissão não descobre a análise
  Given a análise "vendas_mensal" existe, mas não está liberada aos perfis do usuário
  When ele chama execute_vendas_mensal
  Then a resposta é idêntica à de uma análise inexistente (ANALYSIS_NOT_FOUND, mesmo texto)
  And o log registra access_denied com user_id e analysis_id

Scenario: Config DB fora do ar durante call_tool
  Given get_by_name ou is_analysis_allowed levantam exceção
  When o cliente chama a tool
  Then retorna {"status":"error","error_code":"INTERNAL_ERROR",...} e nada vaza para o transporte MCP

Scenario: Isolamento (RNF4)
  Given duas execuções simultâneas e uma falha com timeout
  Then a outra conclui normalmente

Scenario: Compatibilidade
  Then os retornos success e volume_exceeded permanecem idênticos aos da F5/F7
```

## 6. Testes

### 6.1 Testes Unitários (drivers e bancos mockados, como nas F9–F11)

- `schemas/exceptions.py`: cada exceção expõe o `error_code`/`retryable` da tabela da §4.2.
- `retry_async`: sucesso na 1ª; sucesso na 3ª; esgota e relança a última; não repete quando `is_retryable` é falso; backoff 200/400 ms (com `asyncio.sleep` mockado).
- `AnalysisService.execute()`: um teste por linha da tabela da §4.2 (resposta e status gravado); timeout sem retry; erro de SQL sem retry; falha de conexão com retry.
- Contrato por adapter (`tests/test_adapter_contract.py`, já existente): `is_timeout_error`/`is_transient_error` com as exceções reais de cada driver (instanciar a exceção do driver, não um mock genérico).
- `tools.call_tool()`: acesso negado devolve resposta **idêntica** à de análise inexistente (comparar os dois dicts); exceção em `get_by_name`/`is_analysis_allowed` → dict `INTERNAL_ERROR`; `arguments` não-dict; `confirmar_volume_alto` string/número/None.
- `tools.list_tools()`: exceção do repositório não vaza detalhe.
- `AuditService`: grava `timeout` com `error_message`.
- `main.py`: handler global devolve 500 genérico em `/auth/*` sem stack trace.
- Regressão: suítes de F5, F7, F8 e F12 sem alteração de asserts (campos aditivos).

### 6.2 Checklist de Testes

- [x] Todos os testes unitários acima
- [x] Suíte completa verde (475 testes, 6 de 6 execuções após o ajuste do conftest)
- [ ] Manual: no banco existente, rodar `ALTER TABLE execution_history ADD COLUMN error_code VARCHAR(50);` (§4.5) **antes** de subir esta versão; depois, forçar um erro e conferir `status`/`error_code` na linha gravada
- [ ] Manual: SQL Server (sem instância no desenvolvimento): confirmar que uma query lenta devolve `QUERY_TIMEOUT` com o `conn.timeout` definido no `after_created` (decisão 10)
- [ ] Manual: derrubar o `postgres` do compose com o app no ar e chamar uma tool via cliente real (`INTERNAL_ERROR`, app continua de pé)
- [ ] Manual: análise com `pg_sleep` acima do timeout → `QUERY_TIMEOUT` e linha `timeout` no histórico
- [x] Comportamento do SDK `mcp` em exceção conferido no código (1.30.0) e coberto por teste de ponta a ponta no `/mcp` (§4.4)

## 7. Mudanças na Configuração

```
QUERY_RETRY_MAX_ATTEMPTS=3      # total de tentativas (1 = sem retry); validado >= 1 no startup
QUERY_RETRY_BACKOFF_BASE_MS=200 # espera = base * 2^(tentativa-1); validado >= 0
```

Validação em `Settings.model_post_init`, no padrão das variáveis da F7/F12 (falha no startup com mensagem clara). Constar em `.env.example`.

## 8. Documentação

### 8.1 Como a feature aparece no MCP
O cliente continua recebendo um `TextContent` com o JSON do resultado. Em erro, o JSON ganha `error_code` e `retryable`; o LLM usa `retryable` para decidir se reenvia e `error_code` para escolher a mensagem ao usuário.

### 8.2 Como o usuário usa essa feature
Sem ação do usuário. O operador ajusta `QUERY_RETRY_*` e `QUERY_TIMEOUT_SECONDS` no `.env`.

### 8.3 Como outros desenvolvedores estenderão isso
- Novo erro de domínio: criar a exceção em `schemas/exceptions.py` com `error_code`/`retryable` e acrescentar a linha na tabela da §4.2.
- Novo adapter: implementar `is_timeout_error`/`is_transient_error`; sem isso ele não ganha retry nem status `timeout`.
- ARQUITETURA.md ganha a tabela da §4.2; a F16 a reaproveita na documentação da API.

## 9. Checklist de Implementação

- [x] `schemas/exceptions.py` (atributos + 2 exceções novas)
- [x] `services/retry.py`
- [x] `adapters/base.py` + 4 adapters (`is_timeout_error`/`is_transient_error`)
- [x] `analysis_service.py` (resposta com código, status `timeout`, retry no connect e na query)
- [x] `audit_service.py` (status `timeout`)
- [x] `mcp_transport/tools.py` (try, validação de `arguments` e `confirmar_volume_alto`)
- [x] `main.py` (exception handler)
- [x] `config.py` + `.env.example` (`QUERY_RETRY_*`)
- [x] `schema.sql` (comentário de status)
- [x] Testes (§6.1) e suíte completa verde
- [x] `execution_repo.py`/`audit_service.py`/`analysis_service.py`/`schema.sql`: `error_code` no histórico (decisão 12)
- [x] Atualizar ARQUITETURA.md (v1.25, §3.4.1 e DDL), DATABASE_SCHEMA.md (§2.5 + `ALTER TABLE`), NEGOCIO.md (v1.11, RNF4), FEATURES_ROADMAP.md (v1.20), `.claude/CLAUDE.md` (status F14)

## 10. Decisões desta sessão (2026-10-03)

| # | Decisão |
|---|---|
| 1 | Formato do erro: manter o dict e **acrescentar** `error_code` + `retryable`. Não usar `isError` do protocolo (preserva o contrato da F5) |
| 2 | Retry (RNF4: 3x, backoff exponencial) entra, **só** para falha de conexão/transitória; nunca para erro de SQL ou de validação. Tentativas e backoff configuráveis no `.env` |
| 3 | Escopo herdado: entram (1) fechar o contrato "nunca propaga exceção" e (2) distinguir timeout de erro de conexão |
| 4 | **Fora do escopo:** `sslmode` ignorado por PostgreSQL/MySQL (F11 #1) — falha silenciosa de segurança, mudança de comportamento de conexão que pode quebrar data sources existentes; e `translate_params` com `::nome`/literais (F11 #5) — caso extremo que exige tokenizar SQL nos 4 adapters. Sugestão: feature própria ou F15 |
| 5 | Numeração desatualizada (F13/F14/F16) corrigida nas specs F7, F9 e F11 junto desta spec |
| 6 | **P1:** acesso negado e análise inexistente unificados sob `ANALYSIS_NOT_FOUND`, com texto idêntico — o código `ACCESS_DENIED` deixa de existir (conjunto fechado passa a 7 códigos); a distinção fica só no log |
| 7 | **P2:** o `COUNT(*)` do Volume Guard também passa por retry (SELECT idempotente) |
| 9 | **Passo 2 — retry só em falha RÁPIDA de conexão (confirmada):** timeout de **conexão** também fica fora do retry (connect de 30 s × 3 tentativas ≈ 90 s contra host que descarta pacotes). `is_transient_error` cobre só recusada/resetada/perdida, "too many connections" e servidor subindo; `is_timeout_error` e `is_transient_error` são mutuamente exclusivos (teste garante). Substitui "(inclui timeout de conexão)" da §4.3 e da decisão 8 |
| 10 | **SQL Server — timeout de query (confirmada, corrigido na F14):** o `timeout=` do `aioodbc.create_pool` é só o *login timeout* (`SQL_ATTR_LOGIN_TIMEOUT`); a F11 assumia que limitava a query, e nenhum limite era aplicado. O `connect()` passa a usar `after_created` para definir `conn.timeout` (`SQL_ATTR_QUERY_TIMEOUT`) em cada conexão do pool. **Validação manual pendente** (sem instância SQL Server): confirmar que uma query lenta devolve `QUERY_TIMEOUT` |
| 12 | **`error_code` gravado no histórico (confirmada):** coluna `execution_history.error_code VARCHAR(50)`, sem migration — só `schema.sql` + `ALTER TABLE` manual em bancos existentes (§4.5). Inverte a recomendação inicial de não gravar: o precedente do `user_id` (F12) mostra que o projeto aceita esse custo, e sem o código o histórico só distingue `timeout` de "erro qualquer" |
| 11 | **Fora do plano original, durante a implementação:** (a) `execution_time_ms` passa a ser gravado também em erro/timeout (antes `0`); (b) `AnalysisService._with_retry` nunca repete `VolumeExceededError`, independentemente do classificador do adapter; (c) `tests/conftest.py` passa a usar o loop Selector no Windows — a suíte travava no teardown do `TestClient` (loop Proactor), problema anterior à F14 (~1 em 4 execuções no `HEAD`); 24/24 execuções limpas depois do ajuste; (d) `error_response()` é função pública em `schemas/exceptions.py`, usada por `AnalysisService` e `tools.call_tool()` |
| 8 | **P3 (confirmada):** retry automático só em falha de **conexão**; timeout de **query** devolve `QUERY_TIMEOUT` com `retryable: true` e o cliente decide repetir |

**Observações e pendências (fora do escopo da F14):**

| # | Observação | Situação |
|---|---|---|
| 1 | `sslmode` só é respeitado pelo SQL Server (F11 #1) | Pendência — feature futura |
| 2 | `translate_params` casa `::nome` e `:nome` em literais (F11 #5) | Pendência — feature futura |
| 3 | `MySQLAdapter` sem timeout de query (F11 #2) | ✅ Já resolvida no código (`init_command` com `max_execution_time` em `mysql.py`); a spec da F11 foi anotada |
| 4 | Pool do PostgreSQL com 10 conexões por data source (F11 #7) | Pendência — F15 (Performance) |
| 5 | Falhas de autenticação/autorização e `ANALYSIS_NOT_FOUND`/`ACCESS_DENIED` em `call_tool()` só vão para o log, sem linha em `execution_history` (F12 #7) | Aceito em V1.0 |
| 6 | Sem rate limit nem proteção de senha em `/auth/*` (F12 #8) | Fora do escopo; rever antes de expor fora da rede interna |

## 11. Pontos em aberto (a confirmar antes de implementar)

1. ~~`ACCESS_DENIED` × `ANALYSIS_NOT_FOUND`~~ — ✅ resolvido (decisão 6: unificado).
2. ~~Retry no `COUNT(*)`~~ — ✅ resolvido (decisão 7: entra).
3. ~~Timeout de query e retry automático~~ — ✅ resolvido (decisão 8 confirmada): retry automático só em falha **rápida** de conexão (timeout de conexão também fica de fora — decisão 9); o timeout de **query** devolve `QUERY_TIMEOUT` com `retryable: true` e quem decide repetir é o cliente. Motivo: 3 tentativas de uma query de 30 s chegariam a ~90 s, acima do limite de ARQUITETURA.md §8.1 (30 s local / 60 s remoto). O RNF4 ("retry 3x") fica atendido para conexão; a exceção para timeout de query deve ser anotada no NEGOCIO.md.
4. ~~Comportamento do SDK `mcp`~~ — ✅ resolvido no passo 4 (mcp 1.30.0): ver §4.4.
5. ~~`error_code` no histórico~~ — ✅ resolvido (decisão 12): gravado, coluna nova + `ALTER TABLE` manual (§4.5).
6. ~~Exceções reais por driver~~ — ✅ resolvido no passo 2: tabela final na §4.3 (asyncpg, aiomysql, pyodbc conferidos contra as classes instaladas; oracledb conferido no formato do `args[0].full_code`, sem instância Oracle).
