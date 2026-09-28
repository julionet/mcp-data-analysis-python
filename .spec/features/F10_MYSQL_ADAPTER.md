# [F10] MySQL Adapter

## Feature Spec

**ID:** F10
**Nome:** MySQL Adapter
**Prioridade:** 🟡 Média
**Esforço Estimado:** 1d (8h)
**Status:** ⬜ Todo

---

## 1. Visão

Implementa o adapter MySQL para permitir que análises consultem dados em bancos MySQL externos, completando o Factory Pattern iniciado em F2 (PostgreSQL Adapter). Nenhuma mudança em código Python é necessária — apenas registrar a data source MySQL e criar analysis_steps com SQL MySQL no banco de configuração. O SQL é agnóstico de banco, traduzido automaticamente para o formato de cada banco.

## 2. Objetivo

Ter uma implementação `MySQLAdapter` funcional, capaz de conectar, executar queries parametrizadas e normalizar resultado — testada contra um banco MySQL real (servidor do cliente, via credenciais em `data_sources.connection_config`). Refatorar `DatabaseAdapter` para suportar tradução de placeholders por adapter, removendo a dependência hardcoded de PostgreSQL.

**Métrica de Sucesso:**
- ✅ `MySQLAdapter.connect()` abre pool de conexões aiomysql sem erro
- ✅ `MySQLAdapter.execute_query()` retorna `list[dict]` para query parametrizada real
- ✅ Placeholders nomeados (`:param`) em SQL são traduzidos para `?` (MySQL)
- ✅ Nenhuma query é montada por concatenação de string (100% parametrizado)
- ✅ F4 (Execution Engine) executa análises MySQL sem modificação
- ✅ Fluxo end-to-end: criar data_source MySQL → criar analysis/analysis_steps → executar via MCP

## 3. Contexto

**Depende de:** 
- F2 (PostgreSQL Adapter) — interface `DatabaseAdapter` ✅
- F4 (Analysis Execution Engine) — reutiliza adapter do data_source ✅

**É dependência de:** 
- F11 (SQL Server Adapter)
- F9 (MongoDB Adapter) — não, são paralelos

**Decisões confirmadas:**
- Usar `aiomysql` (driver async, valores padrão de pool)
- Usar placeholder `?` (MySQL padrão)
- Credenciais MySQL vêm de `data_sources.connection_config` (JSONB), não de `.env`
- Refatorar `DatabaseAdapter` para adicionar método abstrato `translate_params()`
- Refatorar `PostgreSQLAdapter` para implementar `translate_params()`
- Refatorar `analysis_service.py` para usar `adapter.translate_params()` em vez de função global

---

## 4. Descrição Técnica

### 4.1 Componentes Afetados

```
Componentes novos:
├─ adapters/mysql.py                # MySQLAdapter (aiomysql)
└─ tests/test_mysql_adapter.py      # Testes unitários

Componentes modificados:
├─ adapters/base.py                 # Adiciona método abstrato translate_params()
├─ adapters/postgresql.py           # Implementa translate_params()
├─ adapters/factory.py              # Registra MySQLAdapter
├─ analysis_service.py              # Usa adapter.translate_params()
└─ requirements.txt                 # Adiciona aiomysql
```

### 4.2 Fluxo de Dados

**Registrar data source MySQL (operação manual, fora de código):**
```
Cliente insere em data_sources (via app externo ou SQL direto):
├─ name: "vendas_mysql"
├─ type: "mysql"
├─ connection_config: {host, port, database, user, password (cifrado), sslmode}
└─ is_active: true

Servidor carrega em F4:
├─ AnalysisService._get_adapter(data_source)
├─ AdapterFactory.create_adapter("mysql", config)
└─ Retorna MySQLAdapter(config) já conectado
```

**Executar análise MySQL (fluxo F4, com ajuste de translate_params):**
```
1. Cliente MCP chama call_tool("vendas_por_mes", {...params})
2. AnalysisService.execute(analysis_id, params)
3. AnalysisService._run_query()
   ├─ Carrega analysis (name="vendas_por_mes", data_source_id=uuid_mysql)
   ├─ Carrega steps (SQL nomeado: SELECT ... WHERE mes = :mes)
   ├─ Pega adapter para data_source (MySQLAdapter)
   ├─ adapter.translate_params(sql, ["mes"]) → "SELECT ... WHERE mes = ?"
   ├─ adapter.execute_query(translated_sql, {"mes": "2026-09"})
   │  └─ MySQLAdapter internamente:
   │     ├─ Ordena valores: [validated_params["mes"]]
   │     ├─ cursor.execute("SELECT ... WHERE mes = ?", [value])
   │     └─ Retorna list[dict]
   └─ VolumeGuard, Cache, Audit (idêntico a PostgreSQL)
4. Retorna resultado ao cliente
```

**Método `translate_params()` por adapter:**
```
PostgreSQLAdapter.translate_params(
    "SELECT * FROM vendas WHERE mes = :mes AND ano = :ano",
    ["mes", "ano"]
)
→ "SELECT * FROM vendas WHERE mes = $1 AND ano = $2"

MySQLAdapter.translate_params(
    "SELECT * FROM vendas WHERE mes = :mes AND ano = :ano",
    ["mes", "ano"]
)
→ "SELECT * FROM vendas WHERE mes = ? AND ano = ?"
```

### 4.3 Banco de Dados

**Nenhuma mudança no schema do Config DB.** A tabela `data_sources` já suporta `type='mysql'`:

```sql
-- Já existe em F2, compatível com MySQL:
data_sources (
  id UUID PRIMARY KEY,
  name VARCHAR(255) UNIQUE NOT NULL,
  type VARCHAR(50) NOT NULL,  ← "mysql" agora aceito
  connection_config JSONB NOT NULL,  ← {host, port, database, user, password (Fernet), sslmode}
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- SQL de exemplo (insert manual, sem código Python):
INSERT INTO data_sources (id, name, type, connection_config, is_active)
VALUES (
  gen_random_uuid(),
  'vendas_mysql',
  'mysql',
  '{"host": "192.168.1.20", "port": 3306, "database": "vendas", "user": "readonly", "password": "...(Fernet)...", "sslmode": "prefer"}'::jsonb,
  true
);
```

### 4.4 Endpoints/Interfaces

**Novo arquivo: `adapters/mysql.py`**

```python
class MySQLAdapter(DatabaseAdapter):
    async def connect(self) -> None:
        """Abre o pool de conexões MySQL com valores padrão do aiomysql."""

    async def disconnect(self) -> None:
        """Fecha o pool de conexões."""

    async def execute_query(self, query: str, params: dict | None = None, scalar: bool = False):
        """Executa query parametrizada com placeholders ? (MySQL).
        
        Retorna:
        - scalar=True: valor escalar (ex: COUNT(*))
        - scalar=False (padrão): list[dict], uma linha por dict
        """

    async def execute(self, query: str, *args) -> None:
        """Executa INSERT/UPDATE/DELETE com parâmetros posicionais."""

    async def test_connection(self) -> bool:
        """Testa conexão com SELECT 1."""

    def translate_params(self, sql: str, param_names: list[str]) -> str:
        """Traduz placeholders nomeados (:param) para MySQL (?).
        
        Exemplo:
            input:  "SELECT * FROM t WHERE x = :x AND y = :y", ["x", "y"]
            output: "SELECT * FROM t WHERE x = ? AND y = ?"
        """
```

**Modificação: `adapters/base.py`**

Adicionar método abstrato:
```python
@abstractmethod
def translate_params(self, sql: str, param_names: list[str]) -> str:
    """Traduz placeholders nomeados (:param) para o formato posicional do banco."""
```

**Modificação: `adapters/postgresql.py`**

Implementar:
```python
def translate_params(self, sql: str, param_names: list[str]) -> str:
    """Traduz placeholders nomeados para PostgreSQL ($1, $2, ...)."""
    # Lógica do _translate_named_params existente, migrada aqui
```

**Modificação: `adapters/factory.py`**

```python
_adapters: dict[str, Type[DatabaseAdapter]] = {
    "postgresql": PostgreSQLAdapter,
    "mysql": MySQLAdapter,  # ← NOVO
}
```

**Modificação: `analysis_service.py`**

Remover função global `_translate_named_params()` e ajustar linha ~219:
```python
# Antes:
translated_sql = _translate_named_params(step.definition["sql"], param_names)

# Depois:
translated_sql = adapter.translate_params(step.definition["sql"], param_names)
```

---

## 5. Critérios de Aceitação

```gherkin
Feature: MySQL Adapter

Scenario: Conectar a um banco MySQL no startup
  Given uma data_source com type='mysql' e credenciais válidas
  When AnalysisService._get_adapter(data_source) é chamado
  Then um MySQLAdapter é criado e conectado com sucesso
  And o pool de conexões está pronto para execute_query()

Scenario: Falha de conexão MySQL (fail-fast)
  Given uma data_source com credenciais inválidas
  When AnalysisService._get_adapter() tenta conectar
  Then um DataSourceConnectionError é lançado com mensagem clara
  And a análise retorna {"status": "error", "mensagem": "..."}

Scenario: Executar query parametrizada MySQL
  Given um banco MySQL com tabela "vendas"
  When adapter.execute_query("SELECT * FROM vendas WHERE mes = ?", {"mes": "2026-09"}) é chamado
  Then retorna list[dict] com os registros
  And nenhuma string é concatenada na query (100% parametrizado)

Scenario: Traduzir placeholders nomeados para MySQL
  Given um SQL com placeholders nomeados (":mes", ":ano")
  When adapter.translate_params(sql, ["mes", "ano"]) é chamado
  Then retorna SQL com placeholders ? no lugar de :nomes
  And a ordem de ? preserva a ordem de param_names

Scenario: Executar análise completa MySQL via MCP
  Given uma análise "vendas_mes" consultando data_source MySQL
  And analysis_steps.definition.sql contém placeholders nomeados (":mes")
  When client MCP chama call_tool("vendas_mes", {"mes": "2026-09"})
  Then VolumeGuard, adapter.translate_params(), adapter.execute_query(), e Audit rodam sem erro
  And resultado é retornado com {"status": "success", "data": [...], "cached": false}

Scenario: Pool de conexões é reutilizado
  Given uma data_source MySQL já conectada e cacheada em AnalysisService._adapters
  When duas chamadas consecutivas de execute() usam o mesmo data_source
  Then o mesmo pool é reutilizado (sem abertura/fechamento duplo)
  And execution_history registra ambas as execuções com sucesso

Scenario: Health check reporta status MySQL
  Given um data_source MySQL conectado
  When GET /health é chamado
  Then a resposta inclui "db": true (Config DB PostgreSQL) — MySQL é data source, não reportado em /health
```

---

## 6. Testes

### 6.1 Testes Unitários

**Arquivo: `tests/test_mysql_adapter.py`**

```python
import pytest
import aiomysql
from adapters.mysql import MySQLAdapter

class TestMySQLAdapter:
    
    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Conectar com credenciais válidas."""
        config = {
            "host": "localhost",
            "port": 3306,
            "database": "test_db",
            "user": "test_user",
            "password": "test_pass",
        }
        adapter = MySQLAdapter(config)
        await adapter.connect()
        assert adapter._pool is not None
        await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_connect_invalid_credentials(self):
        """Conectar com credenciais inválidas lança erro."""
        config = {
            "host": "localhost",
            "port": 3306,
            "database": "nonexistent",
            "user": "invalid",
            "password": "invalid",
        }
        adapter = MySQLAdapter(config)
        with pytest.raises(Exception):
            await adapter.connect()

    @pytest.mark.asyncio
    async def test_execute_query_returns_list_of_dicts(self):
        """execute_query retorna list[dict]."""
        adapter = MySQLAdapter({...})
        await adapter.connect()
        rows = await adapter.execute_query("SELECT 1 AS num")
        assert isinstance(rows, list)
        assert all(isinstance(row, dict) for row in rows)
        await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_execute_query_with_params(self):
        """execute_query parametrizado (placeholders ?)."""
        adapter = MySQLAdapter({...})
        await adapter.connect()
        rows = await adapter.execute_query(
            "SELECT ? AS num",
            {"num": 42}
        )
        assert rows[0]["num"] == 42
        await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_execute_query_scalar(self):
        """execute_query com scalar=True retorna um valor."""
        adapter = MySQLAdapter({...})
        await adapter.connect()
        result = await adapter.execute_query(
            "SELECT COUNT(*) FROM (SELECT 1) t",
            scalar=True
        )
        assert result == 1
        await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_test_connection_success(self):
        """test_connection retorna True com banco acessível."""
        adapter = MySQLAdapter({...})
        await adapter.connect()
        result = await adapter.test_connection()
        assert result is True
        await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_test_connection_failure(self):
        """test_connection retorna False com banco inacessível."""
        config = {"host": "nonexistent", "port": 3306, "user": "x", "password": "x", "database": "x"}
        adapter = MySQLAdapter(config)
        result = await adapter.test_connection()
        assert result is False

    def test_translate_params_single(self):
        """Traduz um placeholder nomeado."""
        adapter = MySQLAdapter({})
        sql = "SELECT * FROM t WHERE x = :x"
        result = adapter.translate_params(sql, ["x"])
        assert result == "SELECT * FROM t WHERE x = ?"

    def test_translate_params_multiple(self):
        """Traduz múltiplos placeholders nomeados na ordem correta."""
        adapter = MySQLAdapter({})
        sql = "SELECT * FROM t WHERE x = :x AND y = :y AND z = :z"
        result = adapter.translate_params(sql, ["x", "y", "z"])
        assert result == "SELECT * FROM t WHERE x = ? AND y = ? AND z = ?"

    def test_translate_params_preserves_order(self):
        """Ordem de ? segue param_names, não ordem de aparição no SQL."""
        adapter = MySQLAdapter({})
        sql = "SELECT * FROM t WHERE y = :y AND x = :x"
        result = adapter.translate_params(sql, ["x", "y"])  # ordem diferente do SQL
        # Deve substituir em ordem de param_names: :x → ?, :y → ?
        # Resultado será "SELECT * FROM t WHERE y = ? AND x = ?"
        assert result.count("?") == 2

    @pytest.mark.asyncio
    async def test_execute_insert(self):
        """execute() para INSERT funciona."""
        adapter = MySQLAdapter({...})
        await adapter.connect()
        await adapter.execute(
            "INSERT INTO t (x) VALUES (?)",
            42
        )
        # Validar que foi inserido (query de leitura)
        rows = await adapter.execute_query("SELECT * FROM t WHERE x = 42")
        assert len(rows) > 0
        await adapter.disconnect()
```

### 6.2 Checklist de Testes

- [ ] Teste unitário: conectar com credenciais válidas
- [ ] Teste unitário: conectar com credenciais inválidas (erro)
- [ ] Teste unitário: execute_query retorna list[dict]
- [ ] Teste unitário: execute_query com parâmetros
- [ ] Teste unitário: execute_query scalar=True
- [ ] Teste unitário: test_connection sucesso/falha
- [ ] Teste unitário: translate_params um placeholder
- [ ] Teste unitário: translate_params múltiplos placeholders
- [ ] Teste unitário: translate_params ordem de parâmetros
- [ ] Teste unitário: execute() INSERT/UPDATE/DELETE
- [ ] Teste de integração: AnalysisService com data_source MySQL
- [ ] Teste de integração: fluxo end-to-end (MCP call_tool)
- [ ] Manual: criar data_source MySQL no banco
- [ ] Manual: criar analysis/analysis_steps MySQL
- [ ] Manual: executar via Claude Desktop (ou outro MCP client)

---

## 7. Mudanças na Configuração

**Variáveis de Environment (.env):**
```
# Nenhuma mudança — MySQL vem de data_sources.connection_config
# (Config DB continua PostgreSQL)
```

**Requirements.txt:**
```
aiomysql>=0.2.0
```

**Schema de data_sources.connection_config (exemplo):**
```json
{
  "host": "192.168.1.20",
  "port": 3306,
  "database": "vendas_db",
  "user": "readonly_user",
  "password": "<cifrado com Fernet>",
  "sslmode": "prefer"
}
```

---

## 8. Documentação

### 8.1 Como a feature aparece no MCP
Não aparece diretamente. MySQL é um tipo de data_source interno. As análises que consultam MySQL aparecem normalmente em `list_tools()` (ex: "vendas_por_mes"), com nenhuma diferença visual para o cliente.

### 8.2 Como o usuário usa essa feature
1. Criar entrada em `data_sources` (via SQL ou admin UI futura):
   ```sql
   INSERT INTO data_sources (id, name, type, connection_config)
   VALUES (...);
   ```
2. Criar `analyses` apontando para esse data_source
3. Criar `analysis_steps` com SQL MySQL (placeholders nomeados, ex: `:param`)
4. Usuário final chama análise via MCP como de costume — nenhuma diferença

### 8.3 Como outros desenvolvedores estenderão isso
- Novo adapter (SQL Server, MongoDB) = herdar `DatabaseAdapter`, implementar `connect()`, `disconnect()`, `execute_query()`, `execute()`, `test_connection()`, e **`translate_params()`**
- Registrar no `AdapterFactory._adapters` — sem alterar nenhum outro código

---

## 9. Checklist de Implementação

**Código:**
- [ ] `adapters/base.py` — adicionar método abstrato `translate_params()`
- [ ] `adapters/postgresql.py` — implementar `translate_params()`
- [ ] `adapters/mysql.py` — criar MySQLAdapter completo
- [ ] `adapters/factory.py` — registrar MySQLAdapter
- [ ] `analysis_service.py` — remover `_translate_named_params()` global, usar `adapter.translate_params()`
- [ ] `requirements.txt` — adicionar `aiomysql>=0.2.0`
- [ ] `tests/test_mysql_adapter.py` — testes unitários
- [ ] Code review completo
- [ ] Testes passing (100% dos casos)
- [ ] Docstrings (módulo e métodos públicos)

**QA:**
- [ ] Validar contra MySQL real (servidor do cliente)
- [ ] Fluxo end-to-end: registrar analysis MySQL → executar via MCP
- [ ] Pool de conexões reutilizado corretamente
- [ ] Code review aprovado
- [ ] PR merge aprovado

---

**Documento de Especificação F10 — MySQL Adapter.**
**Sprint 2 — Multi-DB Adapters.**
