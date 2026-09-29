# [F11] SQL Server Adapter

## Feature Spec

**ID:** F11
**Nome:** SQL Server Adapter
**Prioridade:** 🟡 Média
**Esforço Estimado:** 1.5d (12h)
**Status:** ⬜ Todo

---

## 1. Visão

Implementa o adapter SQL Server (`aioodbc` + `pyodbc`) para permitir que análises consultem bancos SQL Server como `data_source`, completando o Factory Pattern iniciado em F2 e continuado em F10. Nenhuma mudança no Execution Engine: o SQL da análise continua escrito com placeholders nomeados (`:param`) e cada adapter traduz para o formato do seu driver.

## 2. Objetivo

Ter um `SQLServerAdapter` funcional — conecta via ODBC, executa queries parametrizadas, normaliza o resultado em `list[dict]` — testado contra o SQL Server real do ambiente de desenvolvimento, e garantir por teste automatizado que o **contrato de parâmetros é idêntico nos três adapters** (PostgreSQL, MySQL, SQL Server).

**Métrica de Sucesso:**
- ✅ `SQLServerAdapter.connect()` abre pool `aioodbc` sem erro (driver ODBC 17 ou 18)
- ✅ `execute_query()` retorna `list[dict]` (ou escalar com `scalar=True`) para query parametrizada real
- ✅ SQL com `:param` — inclusive parâmetro repetido e ordem diferente de `param_names` — executa corretamente
- ✅ Nenhuma query é montada por concatenação de string (100% parametrizado via `?`)
- ✅ F4 (Execution Engine), F3 (Volume Guard), F7 (Cache) e F8 (Audit) funcionam com SQL Server sem modificação
- ✅ `tests/test_adapter_contract.py` passa para PostgreSQL, MySQL e SQL Server com os mesmos cenários
- ✅ Fluxo end-to-end: registrar data_source `sqlserver` → criar analysis/analysis_steps → executar via MCP

## 3. Contexto

**Depende de:**
- F2 (PostgreSQL Adapter) — interface `DatabaseAdapter` ✅
- F4 (Analysis Execution Engine) — reutiliza o adapter do data_source ✅
- F10 (MySQL Adapter) — `translate_params()` abstrato já existe no `DatabaseAdapter` ✅

**É dependência de:**
- F12 (Docker Setup) — instalação do driver ODBC no `Dockerfile` (ver §7.2)
- F9 (Oracle Adapter) — reutiliza `tests/test_adapter_contract.py`, criado aqui
- F16 (Unit Tests) — cobertura dos adapters

**Decisões confirmadas (sessão de 2026-09-28):**
- Driver: `aioodbc` + `pyodbc`. `type` do data_source: `sqlserver` (ARQUITETURA.md §2.2)
- Parâmetro repetido: **Opção 1A** — `translate_params` gera `@nome`; `execute_query` converte para `?` na ordem de ocorrência (contrato do `DatabaseAdapter` não muda)
- `COUNT(*)` do Volume Guard: **Opção 2A** — sem hook novo no `analysis_service`; restrição de SQL documentada (§8.4) e erro traduzido em log
- Driver ODBC: padrão `ODBC Driver 18 for SQL Server`, chave opcional `driver` em `connection_config`
- `sslmode` mapeado para `Encrypt`/`TrustServerCertificate` (§4.4, tabela)
- Autenticação: **somente usuário e senha** do SQL Server (sem Windows/Integrated Auth)
- Teste unitário com mocks; validação manual contra SQL Server local
- Pool: `minsize=1, maxsize=10` (o padrão do `aioodbc` é 10/10 e abriria 10 conexões no primeiro uso — verificado em 2026-09-28); alinhado ao `aiomysql`
- Fora do escopo (registrados em §10): `sslmode` ignorado por PostgreSQL/MySQL; ausência de timeout de query no MySQL

---

## 4. Descrição Técnica

### 4.1 Componentes Afetados

```
Componentes novos:
├─ adapters/sqlserver.py                 # SQLServerAdapter (aioodbc)
├─ tests/test_sqlserver_adapter.py       # Testes unitários do adapter (mocks)
└─ tests/test_adapter_contract.py        # Contrato agnóstico: mesmos cenários em PG, MySQL, SQL Server

Componentes modificados:
├─ adapters/factory.py                   # Registra "sqlserver": SQLServerAdapter
├─ tests/test_adapter_factory.py         # Caso sqlserver
├─ requirements.txt                      # aioodbc>=0.4.0, pyodbc>=5.2.0
├─ .spec/FEATURES_ROADMAP.md             # Status F11, totais Sprint 2, "Bancos suportados"
├─ .spec/ARQUITETURA.md                  # Nota de revisão (F11 implementado, subconjunto SQL comum)
└─ .claude/CLAUDE.md                     # Status Sprint 2 + texto de "SQL agnóstico" (ver §8.4)

Sem mudança:
├─ analysis_service.py, volume_guard_service.py, cache_service.py, audit_service.py
│  (o alias do wrapper de COUNT(*) muda de `AS sub` para `sub` no F9, por causa do Oracle — no F11 nada muda aqui)
├─ adapters/base.py, adapters/postgresql.py, adapters/mysql.py
└─ Schema do Config DB (data_sources.type já aceita 'sqlserver')
```

### 4.2 Fluxo de Dados

**Registrar data source SQL Server (manual, fora de código):**
```
INSERT em data_sources:
├─ name: "vendas_sqlserver"
├─ type: "sqlserver"
├─ connection_config: {host, port, database, user, password (Fernet), sslmode, driver?}
└─ is_active: true
   (password cifrado com scripts/encrypt_credential.py — F10)

AnalysisService._get_adapter(data_source)
├─ decrypt_password(...) → config com senha em claro (só em memória)
├─ AdapterFactory.create_adapter("sqlserver", config)
└─ SQLServerAdapter.connect() → pool aioodbc (cacheado em AnalysisService._adapters)
```

**Executar análise (fluxo F4, sem alterações no service):**
```
1. call_tool("vendas_por_mes", {mes: "2026-09", regiao: null})
2. AnalysisService._run_query()
   ├─ sql = "SELECT ... WHERE mes = :mes AND (:regiao IS NULL OR regiao = :regiao)"
   ├─ translated = adapter.translate_params(sql, ["mes", "regiao"])
   │    → "SELECT ... WHERE mes = @mes AND (@regiao IS NULL OR regiao = @regiao)"
   ├─ count_sql = "SELECT COUNT(*) FROM (<translated>) AS sub"
   ├─ ordered_values = {"mes": "2026-09", "regiao": None}
   ├─ VolumeGuard → adapter.execute_query(count_sql, ordered_values, scalar=True)
   └─ adapter.execute_query(translated, ordered_values)
3. SQLServerAdapter.execute_query() por dentro:
   ├─ varre o SQL por @nome (apenas nomes presentes em params; ignora @@)
   ├─ troca cada ocorrência por "?" e monta a lista de valores NA ORDEM DE OCORRÊNCIA
   │    → "... WHERE mes = ? AND (? IS NULL OR regiao = ?)"  valores: ["2026-09", None, None]
   ├─ cursor.execute(sql, *valores)
   └─ list[dict] montado a partir de cursor.description
```

### 4.3 Banco de Dados

**Nenhuma mudança no schema do Config DB.** `data_sources.type = 'sqlserver'` já está previsto (ARQUITETURA.md §2.2).

```sql
-- Insert manual (sem código Python):
INSERT INTO data_sources (id, name, type, connection_config, is_active)
VALUES (
  gen_random_uuid(),
  'vendas_sqlserver',
  'sqlserver',
  '{"host": "localhost", "port": 1433, "database": "vendas", "user": "readonly",
    "password": "...(Fernet)...", "sslmode": "prefer",
    "driver": "ODBC Driver 17 for SQL Server"}'::jsonb,
  true
);
```

### 4.4 Endpoints/Interfaces

**Novo arquivo: `adapters/sqlserver.py`**

```python
class SQLServerAdapter(DatabaseAdapter):
    async def connect(self) -> None:
        """Abre o pool aioodbc a partir de uma connection string ODBC.

        Chaves de config: host, port (default 1433), database, user, password,
        sslmode (default 'prefer'), driver (default 'ODBC Driver 18 for SQL Server').
        Connection string: DRIVER={driver};SERVER=host,port;DATABASE=...;UID=...;PWD={...};
        Encrypt=...;TrustServerCertificate=...
        - PWD é escapado entre chaves ({...}, '}' → '}}') para suportar ';' e '}' na senha
        - autocommit=True; timeout de query = settings.query_timeout_seconds
        - pool: minsize=1, maxsize=10 (o default do aioodbc é 10/10)
        - sslmode fora da tabela abaixo → ValueError (fail-fast, antes de abrir o pool)
        """

    async def disconnect(self) -> None:
        """Fecha o pool."""

    async def execute_query(self, query: str, params: dict | None = None, scalar: bool = False):
        """Converte @nome → ? (ordem de ocorrência) e executa.

        scalar=True: primeira coluna da primeira linha (None se vazio).
        scalar=False: list[dict], chaves de cursor.description.
        Erros nativos 1033 / 8155 / 8156 (ORDER BY de topo, coluna sem nome,
        coluna duplicada na subquery do COUNT(*)) são relançados com mensagem
        explicando a restrição de SQL (§8.4).
        """

    async def execute(self, query: str, *args) -> None:
        """INSERT/UPDATE/DELETE com parâmetros posicionais (?), autocommit."""

    async def test_connection(self) -> bool:
        """SELECT 1; False em qualquer exceção."""

    def translate_params(self, sql: str, param_names: list[str]) -> str:
        """':x' → '@x' (regex rf':{re.escape(name)}\\b', como nos demais adapters)."""
```

**Mapeamento de `sslmode`:**

| `sslmode` | Connection string ODBC |
|---|---|
| `disable` | `Encrypt=no` |
| `prefer` (padrão se ausente) | `Encrypt=yes;TrustServerCertificate=yes` |
| `verify-full` | `Encrypt=yes;TrustServerCertificate=no` |
| qualquer outro | `ValueError("sslmode '<x>' não suportado para sqlserver")` |

**Conversão `@nome → ?` (interna, `_to_positional(sql, params) -> tuple[str, list]`):**
```
regex: (?<![@\w])@(\w+)
├─ só substitui se o nome estiver em params (@@ROWCOUNT, @variavel_local ficam intactos)
├─ valores na ordem em que os placeholders aparecem no SQL (parâmetro repetido → valor repetido)
└─ limitação conhecida: '@nome' dentro de string literal do SQL também seria substituído
   (mesma categoria do ':nome' dentro de literal nos outros adapters)
```

**Modificação: `adapters/factory.py`**
```python
_adapters = {
    "postgresql": PostgreSQLAdapter,
    "mysql": MySQLAdapter,
    "sqlserver": SQLServerAdapter,  # ← NOVO
}
```

---

## 5. Critérios de Aceitação

```gherkin
Feature: SQL Server Adapter

Scenario: Conectar a um SQL Server no primeiro uso
  Given uma data_source type='sqlserver' com credenciais válidas
  When AnalysisService._get_adapter(data_source) é chamado
  Then um SQLServerAdapter é criado e conectado
  And o pool é reutilizado nas execuções seguintes

Scenario: Falha de conexão (fail-fast)
  Given uma data_source sqlserver com credenciais inválidas ou driver ausente
  When AnalysisService._get_adapter() tenta conectar
  Then DataSourceConnectionError é lançado
  And a análise retorna {"status": "error", "mensagem": "..."}

Scenario: Traduzir placeholders nomeados
  Given SQL "SELECT * FROM t WHERE x = :x AND y = :y"
  When adapter.translate_params(sql, ["x", "y"]) é chamado
  Then retorna "SELECT * FROM t WHERE x = @x AND y = @y"

Scenario: Parâmetro repetido
  Given SQL "WHERE (:termo IS NULL OR desc LIKE :termo)" e params {"termo": "abc"}
  When execute_query é chamado com o SQL traduzido
  Then o driver recebe "WHERE (? IS NULL OR desc LIKE ?)" com valores ["abc", "abc"]

Scenario: Ordem de param_names diferente da ordem no SQL
  Given SQL "WHERE y = :y AND x = :x" e params {"x": 1, "y": 2} (ordem de param_names: x, y)
  When execute_query é chamado
  Then o driver recebe valores [2, 1] (ordem de ocorrência no SQL, não de param_names)

Scenario: Variáveis T-SQL não são tocadas
  Given SQL contendo "@@ROWCOUNT" e "@local" que não estão em params
  When execute_query converte placeholders
  Then "@@ROWCOUNT" e "@local" permanecem inalterados

Scenario: Escalar e lista de dicts
  When execute_query("SELECT COUNT(*) FROM t", scalar=True)
  Then retorna um valor escalar
  When execute_query("SELECT a, b FROM t")
  Then retorna list[dict] com chaves "a" e "b"

Scenario: Senha com caracteres especiais
  Given password = "a;b}c"
  When connect() monta a connection string
  Then PWD={a;b}}c} (escapado) e a conexão não é truncada em ';'

Scenario: sslmode inválido
  Given connection_config.sslmode = "require"
  When connect() é chamado
  Then ValueError é lançado antes de abrir o pool

Scenario: Query fora do subconjunto SQL comum (COUNT(*) do Volume Guard)
  Given análise sqlserver com "SELECT ... ORDER BY x" sem TOP/OFFSET
  When o Volume Guard executa "SELECT COUNT(*) FROM (<sql>) AS sub"
  Then o SQL Server retorna erro 1033
  And o adapter relança com mensagem explicando a restrição (visível no log do servidor)
  And a análise retorna {"status": "error", ...}

Scenario: Contrato agnóstico entre adapters
  Given os mesmos cenários (1 parâmetro, N parâmetros, ordem trocada, parâmetro repetido)
  When executados contra PostgreSQL, MySQL e SQL Server (drivers mockados)
  Then em todos o driver recebe cada valor no ponto certo do SQL

Scenario: Executar análise completa via MCP
  Given análise "vendas_mes" em data_source sqlserver
  When call_tool("vendas_mes", {...})
  Then Volume Guard, translate_params, execute_query e Audit rodam sem erro
  And retorna {"status": "success", "data": [...], "cached": false}
```

---

## 6. Testes

### 6.1 Testes Unitários

**`tests/test_sqlserver_adapter.py`** (driver `aioodbc` mockado, sem SQL Server):

```python
class TestSQLServerAdapter:
    # translate_params
    def test_translate_params_single(self): ...              # :x → @x
    def test_translate_params_multiple(self): ...
    def test_translate_params_word_boundary(self): ...       # :data não casa :data_inicial
    def test_translate_params_empty_list(self): ...
    def test_translate_params_reuse_same_param(self): ...

    # _to_positional (@nome → ?)
    def test_to_positional_occurrence_order(self): ...       # ordem do SQL ≠ ordem do dict
    def test_to_positional_repeated_param(self): ...
    def test_to_positional_ignores_system_variables(self): ...   # @@ROWCOUNT, @local
    def test_to_positional_no_params(self): ...

    # connection string
    def test_connection_string_defaults(self): ...           # driver 18, porta 1433, sslmode prefer
    def test_connection_string_custom_driver(self): ...      # "driver": "ODBC Driver 17 ..."
    def test_connection_string_sslmode_mapping(self): ...    # disable / prefer / verify-full
    def test_connection_string_invalid_sslmode(self): ...    # ValueError
    def test_connection_string_escapes_password(self): ...   # "a;b}c" → {a;b}}c}

    # execução
    @pytest.mark.asyncio
    async def test_connect_passes_autocommit_timeout_and_pool_size(self): ...   # minsize=1, maxsize=10
    @pytest.mark.asyncio
    async def test_execute_query_returns_list_of_dicts(self): ...   # via cursor.description
    @pytest.mark.asyncio
    async def test_execute_query_scalar(self): ...
    @pytest.mark.asyncio
    async def test_execute_query_scalar_empty_returns_none(self): ...
    @pytest.mark.asyncio
    async def test_execute_query_translates_native_error_1033(self): ...   # 1033 / 8155 / 8156
    @pytest.mark.asyncio
    async def test_execute_dml(self): ...
    @pytest.mark.asyncio
    async def test_test_connection_success_and_failure(self): ...
    @pytest.mark.asyncio
    async def test_disconnect_closes_pool(self): ...
```

**`tests/test_adapter_contract.py`** — garantia de comportamento agnóstico:

```python
@pytest.fixture(params=["postgresql", "mysql", "sqlserver"])
def adapter_case(request): ...
# Para cada adapter: instancia com driver mockado e expõe um helper
# `bound_values(sql_with_names, params_dict)` que devolve os valores que o driver
# receberia POR POSIÇÃO/NOME já resolvidos contra o SQL traduzido:
#   PostgreSQL: $n → valor da n-ésima chave de params
#   MySQL:      %(nome)s → params[nome]
#   SQL Server: ? na ordem de ocorrência → valores da lista

CENARIOS = [
    ("SELECT * FROM t WHERE x = :x",                          ["x"],      {"x": 1}),
    ("SELECT * FROM t WHERE x = :x AND y = :y AND z = :z",    ["x","y","z"], {...}),
    ("SELECT * FROM t WHERE y = :y AND x = :x",               ["x","y"],  {"x": 1, "y": 2}),
    ("SELECT * FROM t WHERE (:t IS NULL OR d LIKE :t)",       ["t"],      {"t": "abc"}),
    ("SELECT * FROM t WHERE a = :data AND b = :data_inicial", ["data","data_inicial"], {...}),
]

class TestAdapterContract:
    def test_each_value_lands_on_its_placeholder(self, adapter_case, cenario): ...
    def test_unknown_placeholder_is_left_untouched(self, adapter_case): ...
    @pytest.mark.asyncio
    async def test_execute_query_returns_list_of_dicts(self, adapter_case): ...
    @pytest.mark.asyncio
    async def test_execute_query_scalar_returns_first_value(self, adapter_case): ...
    def test_factory_creates_each_adapter_type(self): ...
```

O helper de PostgreSQL depende de o caller passar `params` na ordem de `param_names` (contrato implícito já assumido pelo `analysis_service`, que monta `ordered_values`). O teste deve **documentar isso explicitamente** para o dia em que alguém mexer nessa montagem.

### 6.2 Checklist de Testes
- [ ] Unitário: `translate_params` (single, múltiplos, word boundary, vazio, repetido)
- [ ] Unitário: `_to_positional` (ordem de ocorrência, repetido, `@@`, `@local`, sem params)
- [ ] Unitário: connection string (defaults, driver custom, sslmode, senha com `;`/`}`)
- [ ] Unitário: `execute_query` lista de dicts / escalar / vazio
- [ ] Unitário: tradução dos erros nativos 1033 / 8155 / 8156
- [ ] Unitário: `execute()` DML, `test_connection`, `disconnect`
- [ ] Contrato: 3 adapters × cenários de parâmetros
- [ ] Factory: `sqlserver` registrado; tipo desconhecido continua levantando `ValueError`
- [ ] Integração: `AnalysisService` com data_source sqlserver (adapter falso)
- [ ] Manual: driver ODBC presente (ver §7.2)
- [ ] Manual: `pip install` de `aioodbc`/`pyodbc` no Python 3.13 sem erro
- [ ] Manual: data_source sqlserver real → `test_connection()` True
- [ ] Manual: análise com parâmetro repetido e com filtro opcional `(:x IS NULL OR ...)` no SQL Server
- [ ] Manual: mesma análise (SQL do subconjunto comum) executada em PG, MySQL e SQL Server com o mesmo resultado
- [ ] Manual: análise com `ORDER BY` de topo → erro claro no log
- [ ] Manual: executar via cliente MCP real

---

## 7. Mudanças na Configuração

### 7.1 Variáveis de Environment (.env)
```
# Nenhuma mudança — credenciais vêm de data_sources.connection_config.
# Timeout de query reutiliza QUERY_TIMEOUT_SECONDS (já existente).
```

### 7.2 Dependências

**`requirements.txt`:**
```
aioodbc>=0.4.0
pyodbc>=5.2.0
```
> Sem pin exato: o `pyodbc==5.0.1` citado antes em ARQUITETURA.md §5.1 não tem wheel para Python 3.13 (ambiente atual: 3.13.2, 64 bits). **Verificado em 2026-09-28** (venv de teste): `aioodbc 0.5.0` e `pyodbc 5.3.0` instalam como wheels binários. ARQUITETURA.md §5.1 já foi atualizada.

**Driver ODBC do sistema operacional (não é `pip install`):**
```
Windows (dev):
  Verificar:  Get-OdbcDriver | Where-Object Name -like '*SQL Server*'
  Ambiente atual (verificado em 2026-09-28): ODBC Driver 17 for SQL Server (64-bit) instalado;
  Driver 18 NÃO instalado → usar "driver": "ODBC Driver 17 for SQL Server" na data_source local.

Linux/Docker (F12): instalar msodbcsql17 ou msodbcsql18 via apt antes do pip install
                     (ARQUITETURA.md §5.1) — entra no Dockerfile do F12.
```

### 7.3 Schema de `connection_config` (SQL Server)
```json
{
  "host": "192.168.1.30",
  "port": 1433,
  "database": "vendas_db",
  "user": "readonly_user",
  "password": "<cifrado com Fernet>",
  "sslmode": "prefer",
  "driver": "ODBC Driver 18 for SQL Server"
}
```
`port`, `sslmode` e `driver` são opcionais (defaults: 1433, `prefer`, Driver 18).

### 7.4 Pré-requisito do banco para o teste manual
A instância precisa aceitar autenticação SQL (modo misto) e ter um login de teste com permissão de leitura — o adapter só suporta usuário e senha. Em 2026-09-28 a instância local (SQL Server 2019, Driver 17) foi sondada apenas com Windows auth (SELECTs); o login por usuário/senha **ainda não foi testado**.

---

## 8. Documentação

### 8.1 Como a feature aparece no MCP
Não aparece diretamente: SQL Server é um tipo de data_source interno. Análises que o consultam aparecem normalmente em `list_tools()`.

### 8.2 Como o usuário usa essa feature
1. Verificar o driver ODBC (§7.2).
2. Cifrar a senha: `scripts/encrypt_credential.py` (F10).
3. Inserir a `data_sources` com `type='sqlserver'` (§4.3).
4. Criar `analyses` e `analysis_steps` com SQL T-SQL usando placeholders `:param`.
5. Chamar a análise via MCP como de costume.

### 8.3 Como outros desenvolvedores estenderão isso
Novo adapter = herdar `DatabaseAdapter`, implementar `connect`, `disconnect`, `execute_query`, `execute`, `test_connection`, `translate_params`, registrar no `AdapterFactory` e **incluir o adapter na fixture de `tests/test_adapter_contract.py`**.

### 8.4 O que é (e o que não é) agnóstico

**Agnóstico (garantido pelos adapters + teste de contrato):** placeholders nomeados `:param` — um, vários, repetidos e em qualquer ordem — e o formato de retorno (`list[dict]` / escalar).

| | PostgreSQL | MySQL | SQL Server | Oracle (F9) |
|---|---|---|---|---|
| Tradução | `:x` → `$n` | `:x` → `%(x)s` | `:x` → `@x` → `?` (na execução) | `:x` → `:pN` (índice em `param_names`) |
| Repetição | reutiliza `$n` | reutiliza `%(x)s` | valor repetido por ocorrência | reutiliza `:pN` |

**Não é traduzido:** o dialeto SQL. `LIMIT` × `TOP`, funções de data, concatenação de strings e casts continuam específicos de cada banco.

**Subconjunto comum de SQL** — para uma mesma análise funcionar nos três bancos, e obrigatório para SQL Server por causa do wrapper `SELECT COUNT(*) FROM (<sql>) AS sub` (`analysis_service.py`):
- ❌ sem `ORDER BY` no nível de topo (SQL Server exige `TOP`/`OFFSET`; o LLM cliente já ordena os dados)
- ❌ sem CTE (`WITH`) no nível de topo (SQL Server não aceita CTE em tabela derivada — erro 156 genérico, **não** traduzido pelo adapter)
- ❌ sem `;` no fim do SQL (o wrapper embute o SQL numa subquery — verificado no SQL Server: erro 102; esperado ORA-00911 no Oracle)
- ✅ todo parâmetro declarado em `step.definition.params` deve aparecer no SQL (PostgreSQL/asyncpg exige o número exato de argumentos e o Oracle deve exigir também; MySQL e SQL Server toleram sobras — regra para manter o mesmo SQL portável entre os 4 bancos)
- ✅ toda coluna do `SELECT` com nome único e explícito (`COUNT(*) AS total`, não `COUNT(*)`) — SQL Server erros 8155/8156, MySQL também rejeita duplicadas
- ⚠️ filtro opcional `(:x IS NULL OR col = :x)`: no PostgreSQL/asyncpg, `$n IS NULL` pode exigir cast explícito e o tipo do cast varia por banco — **validar manualmente** por banco antes de dar a análise por agnóstica

**Onde o erro aparece:** o `AnalysisService` converte qualquer falha de query em `DataSourceConnectionError` com mensagem genérica para o cliente MCP. A mensagem explicando a restrição (1033/8155/8156) fica no **log do servidor** (`logger.exception` + `__cause__`). Tornar essa mensagem visível ao cliente exigiria alterar o service e está **fora do escopo do F11**.

**Verificado em 2026-09-28** (SQL Server 2019, Driver 17, `aioodbc`): os erros 8155, 8156 e 156 aparecem na mensagem como `(8155)`, `(8156)`, `(156)`; o erro do `ORDER BY` em subquery (1033) teve a mensagem confirmada, mas o número não foi capturado — o adapter deve detectar por número **e** por texto ("ORDER BY clause is invalid in views, inline functions, derived tables, subqueries").

**Ajustes de documentação incluídos no F11:**
- `CLAUDE.md`: substituir "mesma query funciona em PostgreSQL ($1, $2) e MySQL (?, ?) automaticamente" por placeholders agnósticos + regra do subconjunto comum; corrigir a menção de que o MySQL usa `?` (usa `%(name)s`).
- `ARQUITETURA.md`: nota de revisão registrando F11 e a regra do subconjunto comum.
- `FEATURES_ROADMAP.md`: status F11, total Sprint 2, métrica "Bancos de Dados Suportados".

---

## 9. Checklist de Implementação

**Código:**
- [ ] `adapters/sqlserver.py` — `SQLServerAdapter` completo
- [ ] `adapters/factory.py` — registrar `sqlserver`
- [ ] `requirements.txt` — `aioodbc`, `pyodbc`
- [ ] `tests/test_sqlserver_adapter.py`
- [ ] `tests/test_adapter_contract.py`
- [ ] `tests/test_adapter_factory.py` — caso sqlserver
- [ ] Docstrings (módulo e métodos públicos)
- [ ] Code review completo
- [ ] Testes passing (100% dos casos, suíte existente sem regressão)

**Docs:**
- [ ] `FEATURES_ROADMAP.md`, `ARQUITETURA.md`, `CLAUDE.md` (§8.4)
- [ ] Esta spec: status 🟩 Done + histórico de implementação

**QA:**
- [ ] Validação manual contra SQL Server local (checklist §6.2)
- [ ] Code review aprovado
- [ ] PR merge aprovado

---

## 10. Observações e Pendências (fora do escopo do F11)

| # | Observação | Situação |
|---|---|---|
| 1 | `PostgreSQLAdapter` e `MySQLAdapter` **ignoram** `sslmode` do `connection_config`; só o SQL Server passa a respeitá-lo. O mesmo campo tem efeito diferente por banco. | Pendência — alinhar em feature futura (ex.: F13 Error Handling & Validation ou ajuste dedicado) |
| 2 | `MySQLAdapter` só configura `connect_timeout`; **não há timeout de query** (PG usa `command_timeout`, SQL Server usa o `timeout` do pyodbc). RNF: máx. 30s local / 60s remoto. | Pendência — corrigir no MySQL em feature futura (ex.: F14 Performance) |
| 3 | `PostgreSQLAdapter` depende de `params` chegar na ordem de `param_names` (`.values()`); MySQL e SQL Server usam o nome. | Registrado no teste de contrato (§6.1) |
| 4 | Mensagem de erro de query é genérica para o cliente MCP (`DataSourceConnectionError`); detalhe só no log. | Comportamento existente, mantido |
| 5 | `translate_params` dos três adapters usa `:nome\b`, que pode casar `::nome` (cast PG, ex.: `x::text` com parâmetro chamado `text`) ou `:nome` dentro de literal. | Caso extremo existente, mantido |
| 6 | `bytes` (VARBINARY) é serializado por `default=str` como `"b'...'"`. | Aceito em V1.0 |
| 7 | `PostgreSQLAdapter` usa os defaults do asyncpg (`min_size=max_size=10`): 10 conexões abertas por data source PostgreSQL. | Pendência — revisar em feature futura (ex.: F14 Performance) |

---

## 11. Verificações Prévias (2026-09-28)

Feitas antes da implementação, com um venv de teste fora do projeto (Python 3.13.2) e a instância SQL Server 2019 local (Driver 17, Windows auth, somente `SELECT`):

- ✅ `aioodbc 0.5.0` / `pyodbc 5.3.0` instalam como wheels binários no Python 3.13
- ✅ Conexão via `aioodbc.create_pool` com o ODBC Driver 17
- ✅ Bind `?` com `None`, valor repetido, `date` e `bool`; `(? IS NULL OR ...)` funciona
- ✅ `cursor.description` fornece os nomes de coluna
- ✅ Erros 8155 (coluna sem nome), 8156 (coluna duplicada) e 156 (CTE de topo) confirmados; `;` no fim do SQL gera erro 102
- ✅ Alias de tabela sem `AS` (`FROM (...) sub`) é aceito — sustenta a troca de `AS sub` para `sub` feita no F9
- ⚠️ `aioodbc.create_pool` abre 10 conexões por padrão (`minsize=10`) — a spec usa `minsize=1, maxsize=10`
- ⏳ Não verificado: login por usuário/senha (modo misto), número 1033 do erro de `ORDER BY`, driver ODBC 18 (não instalado)

---

**Documento de Especificação F11 — SQL Server Adapter.**
**Sprint 2 — Multi-DB Adapters (aguardando implementação).**
