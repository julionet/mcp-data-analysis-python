# [F2] PostgreSQL Adapter

## Feature Spec

**ID:** F2
**Nome:** PostgreSQL Adapter
**Prioridade:** 🔴 Crítica
**Esforço Estimado:** 2d
**Status:** 🟩 Done

---

## 1. Visão

Implementa o adapter de acesso a PostgreSQL — base do Factory Pattern (ARQUITETURA.md §4.2) que será reutilizado por todos os futuros adapters (MySQL, SQL Server, MongoDB). Também estabelece a conexão do servidor com o **Config DB** (`analysis_config`), pré-requisito de toda feature seguinte.

## 2. Objetivo

Ter uma interface `DatabaseAdapter` abstrata e uma implementação `PostgreSQLAdapter` funcional, capaz de conectar, executar queries parametrizadas e normalizar resultado — testada contra um banco Postgres real (criado manualmente, com tabelas de teste).

**Métrica de Sucesso:**
- ✅ `PostgreSQLAdapter.connect()` abre pool de conexões sem erro
- ✅ `PostgreSQLAdapter.execute_query()` retorna `list[dict]` para uma query parametrizada real
- ✅ `/health` reporta status real da conexão ao Config DB
- ✅ Nenhuma query é montada por concatenação de string (100% parametrizada)

## 3. Contexto

**Depende de:** F1 (FastAPI + MCP Server Setup) — ✅ Done
**É dependência de:** F3 (HandlerRegistry — carrega `custom_handlers` do Config DB), F4 (Analysis Execution Engine)

**Decisões confirmadas:**
- Schema do banco (§2.2 do ARQUITETURA.md) é criado **manualmente** — sem Alembic/migrations nesta feature. Migrations ficam para mais perto do fim da V1.0.
- Connection string do Config DB via `.env`, padrão já usado no projeto.
- Pool de conexões com valores padrão do `asyncpg` (sem tuning nesta feature).
- `/health` já inclui `check_postgres()` nesta feature.
- Serão usados **dois bancos Postgres separados**:
  1. **Config DB** (`analysis_config`) — schema manual conforme §2.2, acessado via `.env`.
  2. **Banco de teste** — separado, com tabelas fictícias, criado manualmente por Jose, usado só para validar `execute_query()` de forma isolada (não é uma feature de execução de análise real — isso é F4).

## 4. Descrição Técnica

### 4.1 Componentes Afetados

```
Componentes novos:
├─ adapters/__init__.py
├─ adapters/base.py               # DatabaseAdapter (abstract)
├─ adapters/postgresql.py         # PostgreSQLAdapter (asyncpg)
├─ database/__init__.py
├─ database/connection.py         # Pool de conexão do Config DB (usa PostgreSQLAdapter)
└─ config.py                      # (modificado) adiciona settings do Config DB via .env

Componentes modificados:
└─ main.py                        # startup: abre pool do Config DB / /health: chama check_postgres()
```

### 4.2 Fluxo de Dados

**Startup (parte do fluxo §6.1, passo 2):**
```
FastAPI Startup
└─ 2. Connect to PostgreSQL (config DB)
     ├─ config.py lê POSTGRES_CONFIG_* do .env
     ├─ database/connection.py instancia PostgreSQLAdapter(config)
     ├─ adapter.connect() → cria pool asyncpg (valores padrão)
     └─ Se falhar: log de erro claro, app não sobe (fail-fast)
```

**Uso genérico do adapter (válido tanto para Config DB quanto para data sources futuros em F4):**
```
Chamador (ex.: repository, ou teste manual)
    │
    ├─ adapter.execute_query(sql, params={...})
    │
┌───▼─────────────────────────┐
│ PostgreSQLAdapter           │
│ ├─ 1. Pega conexão do pool  │
│ ├─ 2. asyncpg.fetch(sql,    │
│ │     *params.values())     │  ← parametrizado, nunca f-string
│ ├─ 3. Converte Record→dict  │
│ └─ 4. Libera conexão        │
└───┬─────────────────────────┘
    │
    └─ list[dict] normalizado
```

**Health check (§10.3):**
```
GET /health
└─ check_postgres()
     └─ adapter.test_connection() → SELECT 1
          ├─ sucesso → {"status": "ok", "db": true, ...}
          └─ falha   → {"status": "degraded", "db": false, ...}
```

### 4.3 Banco de Dados

Nenhuma migration nesta feature (decisão confirmada). São necessários **dois bancos Postgres** provisionados manualmente:

1. **Config DB** (`analysis_config`) — com as tabelas do §2.2 (`data_sources`, `analyses`, `analysis_steps`, `analysis_versions`, `custom_handlers`, `execution_history`), na ordem já corrigida no ARQUITETURA.md.
2. **Banco de teste** — separado, com 1-2 tabelas fictícias (ex.: `produtos`, `vendas`), usado apenas para validar `execute_query()` manualmente. Não faz parte do schema oficial da aplicação.

### 4.4 Endpoints/Interfaces

```python
# adapters/base.py
class DatabaseAdapter(ABC):
    def __init__(self, config: dict) -> None:
        self.config = config
        self._pool = None

    @abstractmethod
    async def connect(self) -> None:
        """Abre o pool de conexões."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Fecha o pool de conexões."""

    @abstractmethod
    async def execute_query(self, query: str, params: dict | None = None) -> list[dict]:
        """Executa query parametrizada e retorna resultado normalizado."""

    @abstractmethod
    async def test_connection(self) -> bool:
        """Usado pelo /health e por validações de data_source."""


# adapters/postgresql.py
class PostgreSQLAdapter(DatabaseAdapter):
    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            host=self.config["host"],
            port=self.config["port"],
            user=self.config["user"],
            password=self.config["password"],
            database=self.config["database"],
        )  # min_size/max_size/timeout = defaults do asyncpg

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()

    async def execute_query(self, query: str, params: dict | None = None) -> list[dict]:
        async with self._pool.acquire() as conn:
            records = await conn.fetch(query, *(params or {}).values())
            return [dict(r) for r in records]

    async def test_connection(self) -> bool:
        try:
            await self.execute_query("SELECT 1")
            return True
        except Exception:
            return False
```

```python
# config.py (adição)
class Settings(BaseSettings):
    postgres_config_host: str
    postgres_config_port: int = 5432
    postgres_config_user: str
    postgres_config_password: str
    postgres_config_database: str
```

## 5. Critérios de Aceitação

```gherkin
Feature: PostgreSQL Adapter

Scenario: Conectar ao Config DB no startup
  Given .env com POSTGRES_CONFIG_* configurado corretamente
  When a aplicação FastAPI inicia
  Then o pool de conexões é criado sem erro
  And o startup continua para o próximo passo (Handler Registry)

Scenario: Falha de conexão no startup (fail-fast)
  Given .env com credenciais inválidas do Config DB
  When a aplicação FastAPI inicia
  Then o erro é logado claramente (não stack trace genérico)
  And a aplicação não sobe

Scenario: Executar query parametrizada
  Given um banco Postgres de teste com tabela "produtos"
  When adapter.execute_query("SELECT * FROM produtos WHERE preco > $1", {"preco": 100}) é chamado
  Then retorna list[dict] com os registros correspondentes
  And nenhuma string é concatenada na query

Scenario: Health check reporta status do banco
  Given o Config DB está acessível
  When GET /health é chamado
  Then a resposta inclui "db": true
```

## 6. Testes

### 6.1 Testes Unitários

```python
class TestPostgreSQLAdapter:
    @pytest.mark.asyncio
    async def test_connect_success(self):
        ...

    @pytest.mark.asyncio
    async def test_execute_query_returns_list_of_dicts(self):
        ...

    @pytest.mark.asyncio
    async def test_execute_query_is_parametrized(self):
        # garante que params nunca são interpolados via f-string
        ...

    @pytest.mark.asyncio
    async def test_test_connection_false_on_failure(self):
        ...
```

### 6.2 Checklist de Testes

- [x] Teste unitário: connect com credenciais válidas
- [x] Teste unitário: execute_query com parâmetros
- [x] Teste unitário: test_connection retorna False em falha
- [x] Teste de integração: startup real conectando ao Config DB
- [x] Manual: `curl /health` com banco de teste criado manualmente por Jose

## 7. Mudanças na Configuração

**Variáveis de Environment (.env):**
```
POSTGRES_CONFIG_HOST=localhost
POSTGRES_CONFIG_PORT=5432
POSTGRES_CONFIG_USER=analysis_user
POSTGRES_CONFIG_PASSWORD=secure_password
POSTGRES_CONFIG_DATABASE=analysis_config
```

## 8. Documentação

### 8.1 Como a feature aparece no MCP
Não aparece diretamente ainda — é infraestrutura interna consumida por F3/F4.

### 8.2 Como o usuário usa essa feature
N/A nesta feature (uso indireto via startup e futuros adapters de análise).

### 8.3 Como outros desenvolvedores estenderão isso
Novo adapter (MySQL, SQL Server, MongoDB) = herdar `DatabaseAdapter` e registrar no `AdapterFactory._adapters` (§4.2) — sem alterar código existente.

## 9. Checklist de Implementação

**Código:**
- [x] `adapters/base.py` implementado
- [x] `adapters/postgresql.py` implementado
- [x] `database/connection.py` implementado
- [x] `config.py` atualizado
- [x] `/health` atualizado com `check_postgres()`
- [x] Testes passing (100% dos casos)
- [x] Docstrings

**QA:**
- [ ] Code review aprovado
- [ ] PR merge aprovado
