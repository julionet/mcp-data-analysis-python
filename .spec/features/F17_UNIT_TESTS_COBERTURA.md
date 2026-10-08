# F17 — Unit Tests (80% coverage)

## Feature Spec

**ID:** F17
**Nome:** Testes unitários e cobertura — medição reproduzível, suíte unitária independente de banco e fechamento das lacunas
**Prioridade:** 🟠 Alta
**Esforço Estimado:** ~1d (roadmap original: 2d; revisto em 2026-10-08 porque a meta de 80% já é cumprida — ver §3 e decisão 6)
**Status:** 🟩 Done (2026-10-08)

> **Origem dos requisitos:** FEATURES_ROADMAP.md (linha da F17 e "medir cobertura e preencher lacunas — cobre também F23–F25"; Code Coverage 80%+), NEGOCIO.md §"Testes automatizados (80%+ coverage)", e a **medição feita em 2026-10-08** descrita na §3. Esta spec cobre só a F17; testes de integração com múltiplos clientes MCP são a F18.

---

## 1. Visão

O roadmap pede "80% de cobertura", mas até hoje a cobertura **nunca foi medida**: não há `pytest-cov` no projeto, nem configuração, nem comando documentado. A F17 torna a cobertura **mensurável e reproduzível**, separa o que é teste *unitário* (roda em qualquer máquina, sem Postgres) do que é *integração* (exige o Config DB), fecha as lacunas que a medição apontou — priorizando regras de negócio, não linhas fáceis — e deixa um limite mínimo para a cobertura não regredir.

## 2. Objetivo

Ter um número confiável e repetível de cobertura da suíte **unitária** (sem banco), acima de 80%, com as lacunas de maior risco cobertas e um comando único para medir.

**Métrica de Sucesso:**
- ✅ `pytest-cov` instalado (`requirements-dev.txt`) e configurado (`.coveragerc`): cobertura de `src/` com **branch coverage**
- ✅ A suíte **sem Postgres** passa por inteiro (`0 errors`; testes que dependem de banco real são pulados, não falham) e atinge ≥ **80%** (linhas+branches) — meta do roadmap; limite de regressão em **90%** (decisão 8)
- ✅ A suíte **completa** (com o Config DB do compose) mantém ≥ 95% e todos os testes passam
- ✅ Nenhum módulo de `src/` abaixo de **80%** na suíte unitária (exceto exclusões justificadas na §4.4)
- ✅ Cada lacuna de **risco alto** da §4.3 tem teste que falha se a regra for quebrada (não só executa a linha)
- ✅ Comando e critério documentados (spec §8 e README); nenhuma mudança de comportamento em `src/` (somente testes, configuração e dependência de dev)

## 3. Contexto

**Depende de:** F1–F12 (código testado), F23–F25 (já incluídas na medição)
**É dependência de:** F18 (integração com múltiplos clientes MCP reutiliza fixtures e a separação unit/integration)

### 3.1 Medição de 2026-10-08 (`pytest --cov=src --cov-branch`, 735 testes)

| Cenário | Resultado | Total (stmts+branches) |
|---|---|---|
| **Completa** (Config DB do compose no ar, `localhost:5433`) | 735 passed, 1 skipped, ~14 s | **96%** (2911 stmts, 94 não cobertos; 498 branches, 39 parciais) |
| **Sem banco** (`POSTGRES_CONFIG_PORT=1`) | 697 passed, 19 skipped, **20 errors**, ~21 s | **91%** |

36 dos 57 arquivos de `src/` têm 100%. Os 20 *errors* da execução sem banco não são falhas de teste: a fixture `client` (`tests/conftest.py`, escopo de sessão) abre o `lifespan` real do app, que chama `connect_config_db()` — sem Postgres a fixture levanta `OSError` e **todo teste que a usa quebra em vez de ser pulado** (`test_server_setup.py` — 15, `test_mcp_tools_errors.py::TestThroughTheRealMcpEndpoint` — 2, `test_auth_routes.py`, `test_admin_data_sources_analyses.py::TestWiring`, mais o erro de teardown de `database.connection`). Ou seja: **hoje a suíte não é "unitária"** — só roda inteira com o banco no ar. Os 19 skips são os testes de integração que se pulam sozinhos.

### 3.2 Estado do que existe

- `pytest.ini`: `asyncio_mode = strict`, `testpaths = tests`, `pythonpath = src`; **sem** `markers`, sem `addopts`.
- `requirements-dev.txt`: `pytest`, `pytest-asyncio`, `httpx` — **sem** `pytest-cov`.
- Sem CI no repositório (nada em `.github/`); a verificação é local (`.venv/bin/python -m pytest tests`).
- Os testes de integração se pulam sozinhos (banco indisponível ou tabela ausente), cada um com seu próprio `fixture db`; não há marcador que permita selecioná-los ou excluí-los.
- Repositórios (`*_repo.py`) são cobertos **majoritariamente pela integração**: sem banco caem para 40–66% (`profile_repo` 40%, `analysis_repo` 54%, `data_source_repo` 51%, `user_repo` 52%, `access_token_repo` 66%, `sql_helpers` 22%). A F25 já mostrou o padrão para testá-los sem banco (`tests/test_execution_repo.py::TestExecutionQueries`: adapter `AsyncMock` capturando SQL e a ordem dos valores ligados).

---

## 4. Descrição Técnica

### 4.1 Componentes Afetados

```
Componentes criados/modificados (nenhuma mudança em src/ de comportamento):
├─ requirements-dev.txt            (modificado) + pytest-cov
├─ .coveragerc                     (novo) source=src, branch=true, omit/exclude_lines, [report] fail_under, show_missing
├─ pytest.ini                      (modificado) + markers (integration)
├─ tests/conftest.py               (modificado) fixture `client` sem Config DB (lifespan com banco simulado)
├─ tests/test_*_integration.py     (modificado) marcador `@pytest.mark.integration` (via pytestmark)
├─ tests/test_*_repo*.py           (novos/modificados) SQL e binding dos repositórios sem banco
├─ tests/test_*.py                 (novos/modificados) lacunas de risco alto/médio da §4.3
├─ README.md                       (modificado) como medir cobertura / rodar só unitários
└─ .spec/ (ao concluir)            ROADMAP, CLAUDE.md, NEGOCIO.md (métrica Code Coverage)
```

### 4.2 Fluxo de medição

```
Unitária (sem banco, reproduzível em qualquer máquina):
  .venv/bin/python -m pytest tests -m "not integration" --cov
        └─ lê .coveragerc (src/, branch, fail_under=90) → relatório com linhas faltantes

Completa (Config DB do compose no ar; também roda a integração):
  .venv/bin/python -m pytest tests --cov
```
A **fonte de verdade do limite** é a execução unitária (não depende de ambiente). A completa serve de comparação e para os testes de integração; seu piso (95%) é só verificado na conclusão da F17, não imposto por configuração.

### 4.3 Lacunas identificadas e prioridade

Classificadas por **risco da regra descoberta**, não pelo número de linhas. (Números de linha da medição de 2026-10-08.)

**Risco alto — regra de negócio/segurança sem teste que falharia se quebrada:**

| # | Onde | O que não é coberto | Teste a escrever |
|---|---|---|---|
| A1 | `services/analysis_service.py:257-260` | **Controle de Volume pós-serialização** (`check_serialized_size` → `build_refinement_response`): um dataset que passa no `COUNT(*)` mas estoura o limite em KB depois de serializado deve devolver a resposta de refinamento, não os dados (F3) | análise cujo resultado excede o limite de KB só após serializar → `status` de volume e nada de dados; gravado no histórico como `volume_exceeded` |
| A2 | `schemas/analysis_parameters.py:90,92,114-123` | `min`/`max`/`enum`/`default`/`description` virando **JSON Schema** (o que o cliente MCP/LLM vê no `list_tools`) e `ge`/`le` do modelo de validação | `to_json_schema` com cada atributo (minimum/maximum/enum/default/description/format) e validação rejeitando fora de faixa |
| A3 | `services/analysis_service.py:324,338` | `list_analyses()` (uso interno) e o **double-check do lock** de `_get_adapter` (duas execuções simultâneas criam um único adapter) | 2 chamadas concorrentes com `asyncio.gather` → 1 só `connect()`; `list_analyses` delega ao repositório |
| A4 | `security/auth_middleware.py:65-66`, `mcp_transport/__init__.py:38` | passagem de escopo não-HTTP (lifespan/websocket) sem exigir token; `PermissionError` quando o usuário não está no contexto | escopo `lifespan` atravessa o middleware sem validar; `current_user` ausente levanta `PermissionError` (nunca executa como anônimo) |
| A5 | `database/connection.py:30-38` | falha de conexão do Config DB: log do erro **sem senha** e re-raise (fail-fast do startup) | adapter que falha → `OSError` propagada; `caplog` sem `postgres_config_password` |
| A6 | `services/user_admin_service.py:121,144-169,176…260`, `services/profile_admin_service.py:70-81,92` | corridas de unicidade (`UniqueViolationError` → `EmailAlreadyExists`/`ProfileNameAlreadyExists`), PATCH sem campos, ramos de rebaixamento do último admin | repositório fake que levanta `UniqueViolationError` no `update`/`create`; PATCH vazio devolve o detalhe sem escrever; demais ramos listados na medição |

**Risco médio — comportamento real, impacto contido:**

| # | Onde | Teste |
|---|---|---|
| M1 | `services/cache_backend.py:76,96,100,116` | `set` de chave existente substitui e ajusta `_total_bytes`; purga de expirados libera bytes; `NullBackend.delete` é no-op seguro |
| M2 | `adapters/mysql.py:34-36,56-59,64` | `disconnect()`, `execute()` (commit) e `test_connection()` falso quando a consulta falha — no mesmo padrão dos testes de PostgreSQL/SQL Server |
| M3 | `mcp_transport/tools.py:68-69` | `CACHE_BACKEND=none` instala `NullBackend` e loga o aviso (pode ser testado reimportando o módulo com `settings` ajustado) |
| M4 | `routes/dependencies.py:17-19,23-26,32-35,69-73` | fábricas de dependência dos serviços de usuário, perfil, execuções e `get_user_repo` montam o serviço com o `config_db_adapter` (padrão do `TestWiring` da F24; hoje só as de data source/analyses são testadas) |
| M5 | `routes/admin_route.py:26`, `repositories/sql_helpers.py:7` | `PasswordPolicyError` → 400 `invalid_password`; `like_pattern(None)` e `like_pattern("")` → `None` |

**Repositórios sem banco (risco médio, volume alto — ~150 stmts):** `user_repo`, `profile_repo`, `analysis_repo`, `data_source_repo`, `access_token_repo` e `sql_helpers` só têm cobertura plena com a integração. Cobrir o **SQL e o binding de valores** de cada método com adapter simulado (padrão `TestExecutionQueries`, F25) leva cada um a ≥ 80% sem banco e detecta o erro mais caro: valores ligados na ordem errada de `$n` (o adapter liga o dict por posição). A integração continua sendo a prova de que o SQL roda.

**Risco baixo / tratado por exclusão:**
- `run_https.py` (11 stmts, 0%): ponto de entrada (`uvicorn.run`). Testar o ramo `tls_enabled` e a `alpn_ssl_context_factory` com `uvicorn.run` simulado e `runpy` é barato (decisão 9) e é o que será feito — o arquivo não é excluído da medição.
- `scripts/` (`benchmark.py`, `load_test.py`, `perf_stats.py`, `setup-admin.*`, `build-dist.*`) ficam **fora da medição** (ferramentas operacionais, não código de produto); `tests/test_perf_scripts.py` já protege a lógica pura de `benchmark`/`perf_stats`.

### 4.4 Configuração de cobertura (`.coveragerc`)

```ini
[run]
source = src
branch = True

[report]
fail_under = 90            # decisão 8 — meta do roadmap é 80; 90 protege contra regressão
show_missing = True
skip_covered = True
exclude_lines =
    pragma: no cover
    if __name__ == .__main__.:
    raise NotImplementedError
    \.\.\.$                # corpos de interface/abstrato
```
- **Sem `omit` de módulos** na proposta inicial: nada é escondido para "ajudar" o número. `run_https.py` é **testado** (decisão 9); o bloco `if __name__` só é excluído se o teste via `runpy` não o alcançar. Nunca por `omit` do arquivo inteiro.
- Cada `# pragma: no cover` exige comentário com o motivo (revisado na F17; hoje não há nenhum no `src/`).
- `fail_under` age sobre a execução de `--cov`; vale para o comando unitário (`-m "not integration"`) usado como critério.

### 4.5 Suíte unitária independente de banco

1. **`client` sem Config DB.** A fixture `client` passa a simular `connect_config_db`/`disconnect_config_db`/`check_postgres` (`unittest.mock.patch` nos nomes importados em `main`) para que o `lifespan` suba sem Postgres. Os testes que hoje a usam são de transporte/autenticação/rotas e já substituem os serviços por mocks; nenhum deles testa o banco. O comportamento "sem banco o app não sobe (fail-fast)" ganha um teste próprio (A5), não depende de a fixture falhar.
2. **Marcador `integration`.** `pytest.ini` declara `markers = integration: exige o Config DB (compose local)`; os arquivos `test_*_integration.py` recebem `pytestmark = pytest.mark.integration` (os que já se pulam sozinhos continuam se pulando). `-m "not integration"` é o comando unitário; `pytest tests` continua rodando tudo, como hoje.
3. **Verificação:** `POSTGRES_CONFIG_PORT=1 pytest tests -m "not integration"` não pode ter nenhum `error` nem depender de rede (critério §2).

### 4.6 Convenções para os testes novos

- Mesmos padrões da suíte atual: `pytest.mark.asyncio` (modo strict), `AsyncMock`/fakes em memória (`tests/admin_fakes.py`, `tests/helpers.py`), nomes `test_<comportamento>`. Nada de `time.sleep`, rede ou banco nos testes unitários.
- Um teste novo deve **falhar se a regra for quebrada** (verificado removendo/alterando a linha na hora de escrever); cobrir a linha sem asserção do comportamento não conta (ex.: A1 afirma que os dados **não** vão na resposta).
- Testes de repositório: afirmam a consulta (fragmentos que importam: tabela, `WHERE`, `ORDER BY`, `LIMIT`), a **ordem dos valores ligados** e o mapeamento da linha para o modelo; não duplicam a integração.
- Nenhuma mudança em `src/`. Se um teste revelar bug real, ele é **relatado** (e corrigido só com confirmação, fora do escopo mecânico da F17).

---

## 5. Critérios de Aceitação

```gherkin
Feature: Cobertura de testes unitários

Scenario: Medir a cobertura
  Given O ambiente de desenvolvimento com requirements-dev instalado
  When Rodo `pytest tests -m "not integration" --cov`
  Then Recebo o relatório de linhas e branches de src/ com as linhas faltantes
  And O comando falha se a cobertura ficar abaixo de 90%

Scenario: Suíte unitária sem banco
  Given Nenhum Postgres acessível (POSTGRES_CONFIG_PORT=1)
  When Rodo a suíte unitária
  Then Todos os testes passam, nenhum dá erro e os de integração não são selecionados
  And A cobertura é >= 80% (linhas+branches) e nenhum módulo de src/ fica abaixo de 80%

Scenario: Suíte completa
  Given O Config DB do compose no ar
  When Rodo `pytest tests --cov`
  Then Todos os testes (unitários e de integração) passam e a cobertura é >= 95%

Scenario: Lacunas de risco alto
  When Quebro a regra de cada item A1–A6 (ex.: removo o check_serialized_size, ignoro o min/max do JSON Schema)
  Then Pelo menos um teste novo falha

Scenario: Sem mudança de comportamento
  Then `git diff` em src/ não contém mudanças funcionais (somente, se aplicável, `# pragma: no cover` justificado)

Scenario: Documentação
  Then O README e a spec explicam como medir (unitária e completa) e o limite
```

---

## 6. Testes

### 6.1 Testes novos / ajustados

```python
class TestVolumePostSerialization:     # A1 — passa no COUNT(*), estoura em KB depois de serializar
class TestJsonSchemaConversion:        # A2 — minimum/maximum/enum/default/description/format + validação ge/le
class TestAdapterPoolConcurrency:      # A3 — gather de execuções -> um único connect(); list_analyses delega
class TestAuthMiddlewareScopes:        # A4 — lifespan/websocket sem token; PermissionError sem usuário no contexto
class TestConnectConfigDb:             # A5 — falha loga sem senha e re-levanta
class TestAdminServiceRaces:           # A6 — UniqueViolation em create/update; PATCH vazio; último admin
class TestInMemoryBackendEdges:        # M1 — set de chave existente, purga de expirados, NullBackend.delete
class TestMysqlAdapterLifecycle:       # M2 — disconnect/execute/test_connection falso
class TestCacheBackendNone:            # M3 — CACHE_BACKEND=none
class TestDependencyFactories:         # M4 — fábricas de user/profile/execution/user_repo
class TestSqlHelpersAndAdminRoute:     # M5 — like_pattern(None/""), PasswordPolicyError -> 400
class Test<X>RepoQueries:              # repositórios sem banco (user, profile, analysis, data_source, access_token)
```
Reaproveitar os arquivos de teste existentes de cada módulo quando já houver (não criar arquivo novo por classe).

### 6.2 Checklist de Testes
- [x] `pytest-cov` e `.coveragerc` funcionando; `--cov` mede `src/` com branch
- [x] Fixture `client` sem Config DB; **zero errors** com `POSTGRES_CONFIG_PORT=1`
- [x] Marcador `integration` declarado e aplicado a todos os `test_*_integration.py`
- [x] A1–A6 cobertos com asserção do comportamento
- [x] M1–M5 cobertos
- [x] Repositórios (SQL + ordem dos valores ligados) sem banco: cada um ≥ 80%
- [x] `run_https.py` testado (`uvicorn.run` simulado + `runpy`: TLS ligado/desligado e ALPN factory)
- [x] Unitária ≥ 80% (e ≥ 90% = `fail_under`), nenhum módulo < 80%
- [x] Completa ≥ 95% e verde
- [x] README atualizado

---

## 7. Mudanças na Configuração

- `requirements-dev.txt`: `+ pytest-cov` (apenas desenvolvimento; **não** entra na imagem Docker de produção nem no pacote `dist/`).
- Novo `.coveragerc` e `markers` em `pytest.ini`. `.coverage` e `htmlcov/` entram no `.gitignore`.
- Sem variável de ambiente nova, sem DDL, sem mudança de comportamento em `src/`.

## 8. Documentação

### 8.1 Como medir (README e esta spec)
```
# só unitários, sem banco (critério e limite 90%):
.venv/bin/python -m pytest tests -m "not integration" --cov

# tudo, com o Config DB do compose no ar:
.venv/bin/python -m pytest tests --cov

# relatório HTML opcional:
.venv/bin/python -m pytest tests -m "not integration" --cov --cov-report=html
```
No Windows: `.venv\Scripts\python`.

### 8.2 Para quem escreve código novo
Código novo em `src/` entra com testes unitários; a suíte unitária precisa continuar acima do `fail_under`. Teste que exige banco real recebe `@pytest.mark.integration` (via `pytestmark`) e se pula sozinho quando o banco não está disponível.

### 8.3 Extensões fora do escopo
Integração em CI com Postgres de serviço (a F18/F20 tratam de CI e deploy), mutation testing e teste de carga (F15 já cobre) ficam para depois.

---

## 9. Checklist de Implementação

**Código (somente testes e configuração):**
- [x] `requirements-dev.txt`, `.coveragerc`, `pytest.ini`, `.gitignore`
- [x] `tests/conftest.py` (fixture `client` sem banco) e marcadores
- [x] Testes A1–A6, M1–M5 e dos repositórios
- [x] README

**Documentação (ao concluir):**
- [x] Preencher §12 com antes/depois por módulo; F17 🟩 no ROADMAP e no `.claude/CLAUDE.md`; atualizar "Code Coverage" no ROADMAP e em NEGOCIO.md (de TBD para o valor medido)

**QA:**
- [x] Suíte unitária (sem banco) e completa verdes, com os números acima
- [ ] Code review

---

## 10. Decisões

| # | Decisão | Origem |
|---|---|---|
| 1 | Cobertura medida com `pytest-cov`, **branch coverage**, sobre `src/` | Esta spec (medição 2026-10-08) |
| 2 | A suíte unitária deve rodar **sem banco** e é a referência do critério; integração fica atrás de marcador | Esta spec §3.1 |
| 3 | Prioridade pelas lacunas de **regra de negócio** (A1–A6), não pelo número de linhas | Esta spec §4.3 |
| 4 | Sem `omit` de módulos e sem `# pragma: no cover` sem motivo comentado | Esta spec §4.4 |
| 5 | Nenhuma mudança de comportamento em `src/`; bug achado é relatado e corrigido só com confirmação | Esta spec §4.6 |
| 6 | Esforço reduzido de 2d para ~1d: a meta de 80% já é cumprida (96% completa / 91% sem banco); o trabalho é isolar o banco, fechar lacunas de risco e configurar | Confirmada 2026-10-08 (P1) |
| 7 | Fixture `client` sem Config DB: `connect_config_db`/`disconnect_config_db`/`check_postgres` simulados; os testes que a usam continuam unitários | Confirmada 2026-10-08 (P4) |
| 8 | `fail_under = 90` na suíte unitária (meta oficial do roadmap segue 80%) | Confirmada 2026-10-08 (P2) |
| 9 | `run_https.py` testado com `uvicorn.run` simulado + `runpy`; não é excluído da medição | Confirmada 2026-10-08 (P3) |
| 10 | Repositórios cobertos sem banco por testes de SQL + ordem dos valores ligados (padrão F25); a integração segue como prova de que o SQL roda | Confirmada 2026-10-08 (P5) |

## 11. Pontos em aberto

Nenhum. Os 5 pontos propostos na escrita da spec foram confirmados pelo responsável em 2026-10-08 (todos como propostos) e estão na §10 (decisões 6 a 10):

| # | Ponto | Resolução |
|---|---|---|
| ~~P1~~ | Esforço da F17 | ✅ ~1d (decisão 6) |
| ~~P2~~ | Limite de regressão | ✅ `fail_under = 90` (decisão 8) |
| ~~P3~~ | `run_https.py` | ✅ Testado com `uvicorn.run` simulado + `runpy` (decisão 9) |
| ~~P4~~ | Isolar o banco do `client` | ✅ Simular conexão/desconexão/health na fixture (decisão 7) |
| ~~P5~~ | Repositórios sem banco | ✅ Testes de SQL + ordem dos valores (decisão 10) |

## 12. Implementação

**Resultado (2026-10-08):** 849 testes (848 ✅ + 1 skip pré-existente) com `.venv`, **sem nenhuma mudança em `src/`** (só testes, configuração e dependência de dev). Número de testes: 735 → 849 (+114).

| Medição | Antes (2026-10-08) | Depois |
|---|---|---|
| Unitária, sem banco (`POSTGRES_CONFIG_PORT=1 pytest tests -m "not integration" --cov`) | 91% com **20 errors** | **99,97%** — 829 passed, 20 desmarcados, **0 errors** |
| Completa, com o Config DB do compose (`pytest tests --cov`) | 96% | **99,97%** — 848 passed, 1 skipped |

Por módulo (unitária, sem banco), os que estavam abaixo de 80%: `repositories/sql_helpers` 22% → 100%, `profile_repo` 40% → 100%, `data_source_repo` 51% → 100%, `user_repo` 52% → 100%, `analysis_repo` 54% → 100%, `access_token_repo` 66% → 100%, `routes/dependencies` 64% → 100%, `adapters/postgresql` 69% → 100%, `database/connection` 53% → 100%, `run_https` 0% → 100%. Hoje **todos os módulos estão ≥ 96%**; a única linha parcial é `services/retry.py` `35->exit` (saída do `for` que o próprio laço torna inalcançável com `attempts ≥ 1`), sem `pragma`.

**Arquivos novos:** `.coveragerc`, `tests/test_repositories_queries.py` (38 testes de SQL/binding dos 5 repositórios + `sql_helpers`), `tests/test_admin_service_edges.py` (26: corridas e 404 dos serviços de usuário/perfil), `tests/test_database_connection.py`, `tests/test_run_https.py`. **Modificados:** `requirements-dev.txt` (+`pytest-cov`), `pytest.ini` (marcador `integration`), `.gitignore` (`.coverage`, `htmlcov/`), `tests/conftest.py` (fixture `client` com `connect_config_db`/`disconnect_config_db`/`check_postgres` simulados), os 4 `test_*_integration.py` (`pytestmark`), e classes novas em `test_analysis_service.py` (A1, A3), `test_analysis_parameters.py` (A2), `test_auth_middleware.py` (A4), `test_cache_service.py` (M1), `test_mysql_adapter.py` (M2), `test_mcp_tools.py` (M3), `test_admin_data_sources_analyses.py` (M4, M5 e corridas de FK), `test_postgresql_adapter.py`, `test_oracle_adapter.py`, `test_server_setup.py` (health `degraded`), `README.md` (§7).

**Checagem de mutação (critério "o teste falha se a regra for quebrada"):** quebrei temporariamente 8 regras de risco alto e confirmei que um teste falha em cada uma — A1 (sem `check_serialized_size`), A2 (sem `minimum` e sem `enum` no JSON Schema), A3 (sem o double-check do lock), A4 (escopo não-HTTP autenticado; sem usuário no contexto não levanta), A5 (senha no log) e A6 (`UniqueViolationError` não tratado no create). `src/` restaurado (`git diff` vazio).

**Desvios em relação ao desenho:**
- `.coveragerc` exclui também `def ...: ...` de uma linha (métodos abstratos do `CacheBackend`), além do `...` solto; não há `# pragma: no cover` no código.
- O `run_https.py` entrou como estava (7 stmts, não 11): testado com `uvicorn.run` simulado + `runpy`; nada excluído.
- A fixture `client` simula o Config DB, então `/health` passou a ser testado nos dois estados (`ok` e `degraded`); o fail-fast de verdade ficou em `tests/test_database_connection.py` e o Postgres real nos testes `integration`.
- A unitária (sem banco) já atinge a cobertura da completa: a integração é prova de que o SQL **roda**, não é necessária para o número.
- Nenhum bug de `src/` foi encontrado pelos testes novos.

**Como rodar:** README §7 — `.venv/bin/python -m pytest tests -m "not integration" --cov` (unitária, sem banco, falha abaixo de 90%) e `.venv/bin/python -m pytest tests --cov` (completa).
