# [F9] Oracle Adapter

## Feature Spec

**ID:** F9
**Nome:** Oracle Adapter
**Prioridade:** 🟡 Média
**Esforço Estimado:** 1.5d (12h)
**Status:** 🟩 Done (2026-10-01, sem validação manual)

> **Histórico:** o F9 era "MongoDB Adapter". Em 2026-09-28 o MongoDB foi removido de vez do escopo de V1.0 (sem Backlog Futuro) e o F9 passou a ser o Oracle Adapter — ver FEATURES_ROADMAP.md v1.11, NEGOCIO.md v1.8 e ARQUITETURA.md v1.15. **Implementar depois do F11** (SQL Server).

---

## 1. Visão

Implementa o adapter Oracle (`python-oracledb`, modo thin, async) para permitir que análises consultem bancos Oracle Database como `data_source`, sem exigir Oracle Client no sistema operacional. O SQL da análise continua escrito com placeholders nomeados (`:param`); o adapter traduz para o formato Oracle e normaliza o resultado para o mesmo formato dos demais bancos.

## 2. Objetivo

Ter um `OracleAdapter` funcional — conecta por DSN, executa queries parametrizadas, devolve `list[dict]` com chaves em minúsculas — e incluir o Oracle no teste de contrato (`tests/test_adapter_contract.py`, criado no F11) para garantir que o contrato de parâmetros é o mesmo nos **quatro** adapters (PostgreSQL, MySQL, SQL Server, Oracle).

**Métrica de Sucesso:**
- ✅ `OracleAdapter.connect()` abre pool async (`oracledb.create_pool_async`) a partir de `host`/`port`/`service_name` (ou `sid`)
- ✅ `execute_query()` retorna `list[dict]` (chaves em minúsculas) ou escalar com `scalar=True`
- ✅ SQL com `:param` — inclusive parâmetro repetido e ordem diferente de `param_names` — executa corretamente
- ✅ Nenhuma query montada por concatenação de string (100% bind variables)
- ✅ Wrapper de `COUNT(*)` do Volume Guard funciona nos 4 bancos (`AS sub` → `sub`)
- ✅ F3 (Volume Guard), F4 (Engine), F7 (Cache) e F8 (Audit) funcionam com Oracle sem outra modificação
- ✅ `tests/test_adapter_contract.py` passa para os 4 adapters com os mesmos cenários
- ⏳ Validação manual contra Oracle real — **pendente até existir uma instância** (ver §6.2 e §10)

## 3. Contexto

**Depende de:**
- F2 (PostgreSQL Adapter) — interface `DatabaseAdapter` ✅
- F4 (Analysis Execution Engine) ✅
- F10 (MySQL Adapter) — `translate_params()` abstrato ✅
- F11 (SQL Server Adapter) — cria `tests/test_adapter_contract.py`, ao qual o Oracle é acrescentado

**É dependência de:**
- F17 (Unit Tests) — cobertura dos adapters (renumerado de F16→F17 na revisão v1.12 do roadmap)

**Decisões confirmadas (sessão de 2026-09-28):**
- Driver: `python-oracledb` em **modo thin** (async nativo, Python puro, sem Oracle Client). Modo thick fora do escopo
- Versão alvo: **Oracle Database 12.1+**
- `type` do data_source: `oracle`
- Conexão: o adapter **monta o DSN** (`oracledb.makedsn`) a partir de `host`, `port` (padrão 1521) e `service_name`; `sid` opcional para bancos antigos. `service_name` e `sid` juntos, ou nenhum dos dois → `ValueError`
- Parâmetros (**Opção 2A**): `translate_params` converte `:x` em `:p1`, `:p2`… pelo índice em `param_names` (como o `$n` do PostgreSQL) — evita nome de bind reservado (ORA-01745) e o limite de 30 caracteres do 12.1. Parâmetro repetido reutiliza o mesmo `:pN`
- Chaves de coluna do resultado **normalizadas para minúsculas** (dataset igual nos 4 bancos)
- `analysis_service.py`: alias do wrapper `COUNT(*)` muda de `AS sub` para `sub` (Oracle rejeita `AS` em alias de tabela)
- Pool: `min=1`, `max=10`
- Autenticação: usuário e senha. TNS alias / Wallet / Autonomous DB fora do escopo
- `sslmode`/TCPS **ignorado por enquanto** (igual a PostgreSQL e MySQL)
- Sem instância Oracle no momento: testes unitários com mocks; F9 pode ser dado como **Done sem validação manual**

---

## 4. Descrição Técnica

### 4.1 Componentes Afetados

```
Componentes novos:
├─ adapters/oracle.py                    # OracleAdapter (python-oracledb, thin)
└─ tests/test_oracle_adapter.py          # Testes unitários do adapter (mocks)

Componentes modificados:
├─ adapters/factory.py                   # Registra "oracle": OracleAdapter
├─ services/analysis_service.py          # Linha ~209: "... ) AS sub" → "... ) sub"
├─ tests/test_analysis_service.py        # Asserção do alias do wrapper COUNT(*)
├─ tests/test_adapter_contract.py        # (criado no F11) inclui o Oracle na fixture
├─ tests/test_adapter_factory.py         # Caso oracle
└─ requirements.txt                      # oracledb>=2.0.0

Documentação (a atualizar ao concluir):
├─ .spec/FEATURES_ROADMAP.md             # Status F9, totais Sprint 2, "Bancos suportados"
├─ .spec/ARQUITETURA.md                  # Nota de revisão de conclusão
└─ .claude/CLAUDE.md                     # Status Sprint 2

Já aplicados na sessão de 2026-09-28 (remoção do MongoDB):
├─ NEGOCIO.md v1.8, ARQUITETURA.md v1.15, FEATURES_ROADMAP.md v1.11
├─ DATABASE_SCHEMA.md, database/schema.sql (comentário), adapters/base.py e factory.py (docstrings)
└─ .claude/CLAUDE.md

Sem mudança:
├─ adapters/base.py (contrato), postgresql.py, mysql.py, sqlserver.py
├─ volume_guard_service.py, cache_service.py, audit_service.py
├─ Schema do Config DB (data_sources.type é texto livre, sem CHECK/enum — verificado)
└─ Dockerfile do F13 (thin mode não tem dependência de SO; renumerado de F12→F13
   na revisão v1.12 de FEATURES_ROADMAP.md, que inseriu F12 "Autenticação")
```

### 4.2 Fluxo de Dados

**Registrar data source Oracle (manual, fora de código):**
```
INSERT em data_sources:
├─ name: "vendas_oracle"
├─ type: "oracle"
├─ connection_config: {host, port?, service_name | sid, user, password (Fernet)}
└─ is_active: true
   (password cifrado com scripts/encrypt_credential.py — F10)

AnalysisService._get_adapter(data_source)
├─ decrypt_password(...) → config com senha em claro (só em memória)
├─ AdapterFactory.create_adapter("oracle", config)
└─ OracleAdapter.connect() → pool async (cacheado em AnalysisService._adapters)
```

**Executar análise (fluxo F4):**
```
1. call_tool("vendas_por_mes", {mes: "2026-09", regiao: null})
2. AnalysisService._run_query()
   ├─ sql = "SELECT ... WHERE mes = :mes AND (:regiao IS NULL OR regiao = :regiao)"
   ├─ translated = adapter.translate_params(sql, ["mes", "regiao"])
   │    → "SELECT ... WHERE mes = :p1 AND (:p2 IS NULL OR regiao = :p2)"
   ├─ count_sql = "SELECT COUNT(*) FROM (<translated>) sub"        ← sem AS
   ├─ ordered_values = {"mes": "2026-09", "regiao": None}          ← na ordem de param_names
   ├─ VolumeGuard → adapter.execute_query(count_sql, ordered_values, scalar=True)
   └─ adapter.execute_query(translated, ordered_values)
3. OracleAdapter.execute_query() por dentro:
   ├─ binds = {"p1": "2026-09", "p2": None}   ← {f"p{i}": v for i, v in enumerate(params.values(), 1)}
   ├─ cursor.execute(sql, binds, fetch_lobs=False, fetch_decimals=True)
   └─ list[dict] com chaves = cursor.description[i][0].lower()
```

> Como no PostgreSQL, a associação `:pN` ↔ valor depende de `params` chegar **na ordem de `param_names`** — contrato que o `analysis_service` já cumpre (`ordered_values`) e que o teste de contrato documenta.

### 4.3 Banco de Dados

**Nenhuma mudança no schema do Config DB.** `data_sources.type` é `VARCHAR(50)` sem `CHECK` (verificado em `database/schema.sql`) e não há enum/`Literal` no código.

```sql
INSERT INTO data_sources (id, name, type, connection_config, is_active)
VALUES (
  gen_random_uuid(),
  'vendas_oracle',
  'oracle',
  '{"host": "192.168.1.40", "port": 1521, "service_name": "ORCLPDB1",
    "user": "readonly", "password": "...(Fernet)..."}'::jsonb,
  true
);
-- Banco antigo, por SID:  {"host": "...", "port": 1521, "sid": "ORCL", ...}
```

### 4.4 Endpoints/Interfaces

**Novo arquivo: `adapters/oracle.py`**

```python
class OracleAdapter(DatabaseAdapter):
    async def connect(self) -> None:
        """Abre o pool async do python-oracledb (thin mode).

        Chaves de config: host, port (default 1521), user, password e exatamente
        UMA entre service_name e sid — ambas ou nenhuma → ValueError (antes de abrir o pool).
        DSN: oracledb.makedsn(host, port, service_name=... | sid=...)
        Pool: create_pool_async(user, password, dsn, min=1, max=10,
                                tcp_connect_timeout=settings.query_timeout_seconds)
        """

    async def disconnect(self) -> None:
        """Fecha o pool."""

    async def execute_query(self, query: str, params: dict | None = None, scalar: bool = False):
        """Bind por índice (:pN ← params.values() na ordem recebida) e executa.

        - call_timeout da conexão = settings.query_timeout_seconds * 1000 (ms)
        - fetch_lobs=False (CLOB → str, BLOB → bytes; o default do driver devolveria objetos LOB)
        - fetch_decimals=True (NUMBER → Decimal, como PostgreSQL/MySQL/SQL Server; serializado por default=str)
        - scalar=True: primeira coluna da primeira linha (None se vazio)
        - scalar=False: list[dict] com chaves em minúsculas (cursor.description)
        - ORA-00918 (coluna ambígua/duplicada na subquery do COUNT) e ORA-00911 (';' no SQL) são
          relançados com mensagem explicando a restrição de SQL (§8.4)
        """

    async def execute(self, query: str, *args) -> None:
        """INSERT/UPDATE/DELETE com binds posicionais (:1, :2...) + commit explícito."""

    async def test_connection(self) -> bool:
        """SELECT 1 FROM DUAL (Oracle exige FROM; só o 23ai dispensa); False em qualquer exceção."""

    def translate_params(self, sql: str, param_names: list[str]) -> str:
        """':x' → ':p{n}' (n = índice de 'x' em param_names, base 1), regex rf':{re.escape(name)}\\b'."""
```

**Modificação: `adapters/factory.py`**
```python
_adapters = {
    "postgresql": PostgreSQLAdapter,
    "mysql": MySQLAdapter,
    "sqlserver": SQLServerAdapter,   # F11
    "oracle": OracleAdapter,         # ← NOVO
}
```

**Modificação: `services/analysis_service.py` (~linha 209)**
```python
# Antes:
count_sql = f"SELECT COUNT(*) FROM ({translated_sql}) AS sub"
# Depois:
count_sql = f"SELECT COUNT(*) FROM ({translated_sql}) sub"
```
Alias sem `AS` é aceito por PostgreSQL, MySQL, SQL Server (**verificado em 2026-09-28**, F11 §11) e Oracle (que rejeita `AS` em alias de tabela — ORA-00933).

---

## 5. Critérios de Aceitação

```gherkin
Feature: Oracle Adapter

Scenario: Conectar por service_name
  Given uma data_source type='oracle' com host, service_name, user e password
  When AnalysisService._get_adapter(data_source) é chamado
  Then um OracleAdapter é criado e o pool é aberto com DSN de service_name
  And o pool é reutilizado nas execuções seguintes

Scenario: Conectar por SID (banco antigo)
  Given connection_config com "sid" e sem "service_name"
  When connect() é chamado
  Then o DSN é montado com SID

Scenario: service_name e sid informados juntos, ou nenhum
  When connect() é chamado
  Then ValueError é lançado antes de abrir o pool

Scenario: Falha de conexão (fail-fast)
  Given credenciais inválidas ou host inacessível
  When AnalysisService._get_adapter() tenta conectar
  Then DataSourceConnectionError é lançado
  And a análise retorna {"status": "error", "mensagem": "..."}

Scenario: Traduzir placeholders nomeados
  Given SQL "SELECT * FROM t WHERE x = :x AND y = :y"
  When adapter.translate_params(sql, ["x", "y"]) é chamado
  Then retorna "SELECT * FROM t WHERE x = :p1 AND y = :p2"

Scenario: Parâmetro repetido
  Given SQL "WHERE (:termo IS NULL OR desc LIKE :termo)" e param_names ["termo"]
  When translate_params e execute_query são chamados com {"termo": "abc"}
  Then o SQL vira "WHERE (:p1 IS NULL OR desc LIKE :p1)" e o driver recebe binds {"p1": "abc"}

Scenario: Nome de parâmetro é palavra reservada do Oracle
  Given param_names ["date", "level"]
  When translate_params é chamado
  Then o SQL usa :p1 e :p2 (nenhum nome reservado chega ao Oracle)

Scenario: Nomes de coluna em minúsculas
  Given "SELECT NOME, Total FROM t"
  When execute_query retorna
  Then as chaves dos dicts são "nome" e "total"

Scenario: LOB e NUMBER
  When a query retorna uma coluna CLOB e uma NUMBER
  Then execute é chamado com fetch_lobs=False e fetch_decimals=True

Scenario: test_connection
  When test_connection() é chamado
  Then executa "SELECT 1 FROM DUAL" e retorna True/False

Scenario: Wrapper COUNT(*) sem AS
  Given qualquer análise
  When o Volume Guard monta o count_sql
  Then o SQL termina com ") sub" e não contém " AS sub"
  And a suíte de testes de PostgreSQL, MySQL e SQL Server continua passando

Scenario: SQL fora do subconjunto comum
  Given análise Oracle com ';' no fim do SQL, ou colunas duplicadas na SELECT
  When o Volume Guard executa o COUNT(*)
  Then o Oracle retorna ORA-00911 / ORA-00918
  And o adapter relança com mensagem explicando a restrição (visível no log do servidor)

Scenario: Contrato agnóstico entre adapters
  Given os mesmos cenários (1 parâmetro, N parâmetros, ordem trocada, parâmetro repetido, prefixo de nome)
  When executados contra PostgreSQL, MySQL, SQL Server e Oracle (drivers mockados)
  Then em todos o driver recebe cada valor no ponto certo do SQL

Scenario: Executar análise completa via MCP  (manual, quando houver instância)
  Given análise "vendas_mes" em data_source oracle
  When call_tool("vendas_mes", {...})
  Then retorna {"status": "success", "data": [...], "cached": false}
```

---

## 6. Testes

### 6.1 Testes Unitários

**`tests/test_oracle_adapter.py`** (`oracledb` mockado, sem banco):

```python
class TestOracleAdapter:
    # translate_params
    def test_translate_params_single(self): ...              # :x → :p1
    def test_translate_params_multiple(self): ...            # :x,:y,:z → :p1,:p2,:p3
    def test_translate_params_follows_param_names_index(self): ...   # ordem de param_names ≠ ordem no SQL
    def test_translate_params_word_boundary(self): ...       # :data não casa :data_inicial
    def test_translate_params_reserved_word_names(self): ... # :date, :level → :pN
    def test_translate_params_empty_list(self): ...
    def test_translate_params_reuse_same_param(self): ...

    # conexão
    def test_dsn_from_service_name(self): ...
    def test_dsn_from_sid(self): ...
    def test_dsn_default_port_1521(self): ...
    def test_dsn_both_service_name_and_sid_raises(self): ...
    def test_dsn_neither_service_name_nor_sid_raises(self): ...
    @pytest.mark.asyncio
    async def test_connect_pool_args(self): ...              # min=1, max=10, tcp_connect_timeout

    # execução
    @pytest.mark.asyncio
    async def test_execute_query_binds_by_index(self): ...   # {"p1":..., "p2":...} na ordem recebida
    @pytest.mark.asyncio
    async def test_execute_query_lowercases_keys(self): ...
    @pytest.mark.asyncio
    async def test_execute_query_passes_fetch_lobs_false_and_decimals_true(self): ...
    @pytest.mark.asyncio
    async def test_execute_query_sets_call_timeout_ms(self): ...
    @pytest.mark.asyncio
    async def test_execute_query_scalar(self): ...
    @pytest.mark.asyncio
    async def test_execute_query_scalar_empty_returns_none(self): ...
    @pytest.mark.asyncio
    async def test_execute_query_translates_ora_00911_and_00918(self): ...
    @pytest.mark.asyncio
    async def test_execute_dml_commits(self): ...
    @pytest.mark.asyncio
    async def test_test_connection_uses_dual(self): ...
    @pytest.mark.asyncio
    async def test_disconnect_closes_pool(self): ...
```

**`tests/test_adapter_contract.py`** (criado no F11) — acrescentar `"oracle"` em `params=[...]` da fixture e o helper do Oracle (`:pN` → n-ésimo valor de `params.values()`, igual ao PostgreSQL). Os cenários existentes valem sem alteração.

**`tests/test_analysis_service.py`** — nova asserção: o `count_sql` enviado ao adapter termina com `) sub` e não contém ` AS sub`.

### 6.2 Checklist de Testes
- [x] Unitário: `translate_params` (single, múltiplos, índice, word boundary, palavra reservada, vazio, repetido)
- [x] Unitário: DSN por `service_name` / `sid` / porta padrão / erros de configuração
- [x] Unitário: binds por índice, chaves minúsculas, `fetch_lobs`/`fetch_decimals`, `call_timeout`, escalar
- [x] Unitário: tradução de ORA-00911 / ORA-00918
- [x] Unitário: `execute()` com commit, `test_connection` (DUAL), `disconnect`
- [x] Contrato: 4 adapters × cenários de parâmetros
- [x] Factory: `oracle` registrado; tipo desconhecido continua levantando `ValueError`
- [x] Regressão: suíte completa (PostgreSQL, MySQL, SQL Server) passa com `AS sub` → `sub`
- [ ] Manual (quando houver instância — **pendente**): `test_connection()` True
- [ ] Manual (pendente): parâmetro repetido e filtro opcional `(:x IS NULL OR ...)`
- [ ] Manual (pendente): tipos NUMBER (int/decimal), DATE (datetime), CLOB (str) no JSON final
- [ ] Manual (pendente): declarar parâmetro que não aparece no SQL (esperado: erro do driver — ver §8.4)
- [ ] Manual (pendente): mesma análise (subconjunto comum) em PG, MySQL, SQL Server e Oracle com o mesmo resultado
- [ ] Manual (pendente): executar via cliente MCP real

---

## 7. Mudanças na Configuração

### 7.1 Variáveis de Environment (.env)
```
# Nenhuma mudança — credenciais vêm de data_sources.connection_config.
# Timeout reutiliza QUERY_TIMEOUT_SECONDS (já existente).
```

### 7.2 Dependências

**`requirements.txt`:**
```
oracledb>=2.0.0
```
> Verificado em 2026-09-28 (venv de teste, Python 3.13.2): `oracledb 26.0.1` instala como wheel binário, roda em modo thin por padrão e expõe `create_pool_async`, `connect_async`, `makedsn(service_name=|sid=)`, `AsyncConnection.call_timeout` e o parâmetro `fetch_lobs`/`fetch_decimals` em `cursor.execute`. O piso `>=2.0.0` (primeira versão com asyncio, a confirmar) deve ser validado no `pip install`.

**Sem dependência de sistema operacional:** thin mode dispensa Oracle Client/Instant Client — o `Dockerfile` do F13 não muda por causa do Oracle.

### 7.3 Schema de `connection_config` (Oracle)
```json
{
  "host": "192.168.1.40",
  "port": 1521,
  "service_name": "ORCLPDB1",
  "user": "readonly_user",
  "password": "<cifrado com Fernet>"
}
```
`port` é opcional (padrão 1521). Use `"sid"` **no lugar de** `"service_name"` para bancos antigos. Chaves extras (ex.: `sslmode`) são ignoradas.

---

## 8. Documentação

### 8.1 Como a feature aparece no MCP
Não aparece diretamente: Oracle é um tipo de data_source interno. Análises que o consultam aparecem normalmente em `list_tools()`.

### 8.2 Como o usuário usa essa feature
1. Cifrar a senha: `scripts/encrypt_credential.py` (F10).
2. Inserir a `data_sources` com `type='oracle'` (§4.3).
3. Criar `analyses` e `analysis_steps` com SQL Oracle usando placeholders `:param`.
4. Chamar a análise via MCP como de costume.

### 8.3 Como outros desenvolvedores estenderão isso
Novo adapter = herdar `DatabaseAdapter`, implementar os 6 métodos, registrar no `AdapterFactory` e incluí-lo na fixture de `tests/test_adapter_contract.py`.

### 8.4 O que é (e o que não é) agnóstico

**Agnóstico (garantido pelos adapters + teste de contrato):** placeholders nomeados `:param` — um, vários, repetidos, em qualquer ordem — e o formato de retorno (`list[dict]` com chaves em minúsculas / escalar).

| | PostgreSQL | MySQL | SQL Server | Oracle |
|---|---|---|---|---|
| Tradução | `:x` → `$n` | `:x` → `%(x)s` | `:x` → `@x` → `?` | `:x` → `:pN` |
| Repetição | reutiliza `$n` | reutiliza `%(x)s` | valor repetido por ocorrência | reutiliza `:pN` |
| Associação valor↔placeholder | ordem do dict | nome | nome (ocorrência) | ordem do dict |

**Não é traduzido:** o dialeto SQL (`LIMIT` × `TOP` × `FETCH FIRST n ROWS ONLY`, funções de data, concatenação, casts).

**Subconjunto comum de SQL** — para a mesma análise rodar nos 4 bancos (obrigatório por causa do wrapper `SELECT COUNT(*) FROM (<sql>) sub`):
- ❌ sem `ORDER BY` no nível de topo (SQL Server exige `TOP`/`OFFSET`)
- ❌ sem CTE (`WITH`) no nível de topo (SQL Server)
- ❌ sem `;` no fim do SQL (SQL Server erro 102; Oracle ORA-00911)
- ✅ toda coluna do `SELECT` com nome único e explícito (`COUNT(*) AS total`) — SQL Server 8155/8156, MySQL, Oracle ORA-00918
- ✅ todo parâmetro declarado em `step.definition.params` deve aparecer no SQL (PostgreSQL exige; Oracle deve exigir — *não testado*; MySQL e SQL Server toleram)
- ⚠️ filtro opcional `(:x IS NULL OR col = :x)`: pode exigir cast no PostgreSQL (o tipo do cast varia por banco) — **validar manualmente** por banco

**Particularidades do Oracle (não tratadas pelo adapter):**
- String vazia é `NULL` — `(:x IS NULL OR ...)` com `""` se comporta como "sem filtro"
- Antes do Oracle 23ai não existe tipo booleano em SQL: um parâmetro `boolean` da análise pode falhar ao ser vinculado
- `DATE` do Oracle inclui hora (volta como `datetime`)
- Nomes de coluna de retorno são normalizados para minúsculas — duas colunas que diferem só por caixa (ex.: `"A"` e `"a"` com aspas) colidem

**Onde o erro aparece:** o `AnalysisService` converte qualquer falha de query em `DataSourceConnectionError` com mensagem genérica para o cliente MCP; a explicação da restrição (ORA-00911/ORA-00918) fica no **log do servidor**. Tornar a mensagem visível ao cliente exigiria alterar o service — fora do escopo.

---

## 9. Checklist de Implementação

**Código:**
- [x] `adapters/oracle.py` — `OracleAdapter` completo
- [x] `adapters/factory.py` — registrar `oracle`
- [x] `services/analysis_service.py` — `AS sub` → `sub`
- [x] `requirements.txt` — `oracledb>=2.0.0`
- [x] `tests/test_oracle_adapter.py`
- [x] `tests/test_adapter_contract.py` — incluir Oracle
- [x] `tests/test_analysis_service.py` — asserção do alias
- [x] `tests/test_adapter_factory.py` — caso oracle
- [x] Docstrings (módulo e métodos públicos)
- [ ] Code review completo
- [x] Testes passing (100% dos casos, suíte existente sem regressão)

**Docs:**
- [x] `FEATURES_ROADMAP.md`, `ARQUITETURA.md`, `CLAUDE.md`
- [x] Esta spec: status 🟩 Done (sem validação manual) + histórico de implementação
- [x] `adapters/base.py` — acrescentar exemplos SQL Server/Oracle em `translate_params` (docstring)

**QA:**
- [ ] Validação manual contra Oracle real — **pendente até existir instância**
- [ ] Code review aprovado
- [ ] PR merge aprovado

---

## 10. Observações e Pendências (fora do escopo do F9)

| # | Observação | Situação |
|---|---|---|
| 1 | Sem instância Oracle: comportamento de bind repetido, ORA-00933/00911/00918, unused-param, tipos NUMBER/DATE/CLOB e booleano **não foram testados** — vêm da documentação do driver e do Oracle. | Validação manual pendente; F9 sai como "Done sem validação manual" |
| 2 | `sslmode`/TCPS ignorado (igual a PostgreSQL e MySQL). | Pendência compartilhada — ver F11 §10 item 1 |
| 3 | Modo thick, TNS alias, Wallet/Autonomous DB, Oracle < 12.1. | Fora de escopo em V1.0 |
| 4 | Mensagem de erro de query é genérica para o cliente MCP; detalhe só no log. | Comportamento existente, mantido |
| 5 | `translate_params` usa `:nome\b`, que também casaria `:nome` dentro de um literal de string (ex.: `TO_DATE(x, 'HH24:MI')` com um parâmetro chamado `mi`). | Caso extremo, mantido |
| 6 | `fetch_decimals=True` faz `NUMBER` voltar como `Decimal` (serializado como string por `default=str`, igual aos outros bancos). Comportamento para colunas `NUMBER` inteiras a confirmar na instância real. | Validar no teste manual |
| 7 | MongoDB removido de V1.0 sem Backlog Futuro (decisão de 2026-09-28). | Registrado em ROADMAP v1.11 / NEGOCIO v1.8 / ARQUITETURA v1.15 |
| 8 | Specs históricas (F2, F4, F10) ainda citam MongoDB como exemplo de adapter futuro. | Mantidas — refletem o momento em que foram escritas |

---

## 11. Histórico de Implementação

### ✅ Implementação Completada (2026-10-01)

**Arquivos criados:**
- ✅ `src/adapters/oracle.py` — `OracleAdapter`: `_build_dsn()`, `connect()`/`disconnect()`, `_to_binds()`, `execute_query()`, `execute()`, `test_connection()`, `translate_params()`
- ✅ `tests/test_oracle_adapter.py` — 27 testes unitários com `oracledb` mockado

**Arquivos modificados:**
- ✅ `src/adapters/factory.py` — `"oracle": OracleAdapter`
- ✅ `src/services/analysis_service.py` — `count_sql` com alias `sub` (sem `AS`)
- ✅ `requirements.txt` — `oracledb>=2.0.0` (instalado: 26.0.1)
- ✅ `src/adapters/base.py` e `sqlserver.py` — só docstrings/comentários (exemplos SQL Server/Oracle; alias do wrapper)
- ✅ `tests/test_adapter_contract.py` — fixture com 4 adapters (o mock do Oracle devolve colunas em MAIÚSCULAS para provar a normalização)
- ✅ `tests/test_adapter_factory.py` — caso `oracle`; o teste de "tipo desconhecido" passou a usar `mongodb` (antes usava `oracle`, que agora é válido)
- ✅ `tests/test_analysis_service.py` — asserção `) sub` / sem ` AS sub`
- ✅ `.spec/FEATURES_ROADMAP.md` (v1.16), `.spec/ARQUITETURA.md` (v1.23), `.claude/CLAUDE.md`

**Testes:** 334/334 na suíte completa (27 novos em `test_oracle_adapter.py` + Oracle nos testes de contrato e de factory), sem regressão.

### Decisões de implementação (dentro do que a spec definiu)
- `connect()` valida o DSN **antes** de abrir o pool e, depois de `create_pool_async` (preguiçoso), faz um `acquire` de teste para o fail-fast do §5 valer de fato; se falhar, o pool é fechado com `force=True` e o erro é relançado (`_pool` fica `None`).
- `translate_params` substitui em **passo único** (regex `(?<![\w:]):(\w+)` + mapa nome→índice), em vez de um `re.sub` por nome: um parâmetro chamado `p1` não corrompe um `:p1` já gerado. Placeholder fora de `param_names` fica intacto (exigência do teste de contrato).
- ORA-00911/ORA-00918 viram `RuntimeError` com a explicação do §8.4 (erro nativo em `__cause__`), como no SQL Server; demais erros são relançados sem alteração.
- A spec não pedia o `acquire` de validação nem `force=True` no fechamento do pool — são ajustes de implementação.

### Validação manual
⏳ **Pendente** — sem instância Oracle (itens "Manual" do §6.2 e Observação 1 do §10).

---

**Documento de Especificação F9 — Oracle Adapter.**
**Sprint 2 — Multi-DB Adapters (implementar após F11).**
