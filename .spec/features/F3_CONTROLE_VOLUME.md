# [F3] Controle de Volume de Resultado

## Feature Spec Template

**ID:** F3
**Nome:** Controle de Volume de Resultado
**Prioridade:** 🔴 Crítica
**Esforço Estimado:** 1d (8h)
**Status:** 🟩 Done

> **Ajuste retroativo (F5, 2026-09-24):** status de recusa renomeado de `refinamento_necessario` para `volume_exceeded` (mesmo payload, só o nome mudou), para bater com o texto já aprovado da spec F5. Ver F5_MCP_TOOLS_INTEGRATION.md §10.

---

## 1. Visão
Serviço que impede o servidor de devolver ao cliente MCP um dataset grande demais (em linhas ou em KB serializado), recusando a execução com uma resposta estruturada de refinamento antes de buscar dados em excesso.

## 2. Objetivo
Evitar que uma análise sem filtros suficientes estoure o contexto/custo de tokens do cliente MCP, já que o servidor não transforma mais os dados (ADR-005) — o dataset bruto vai inteiro para o LLM do cliente.

**Métrica de Sucesso:**
- ✅ Nenhuma execução devolve resultado acima de `DEFAULT_MAX_RESULT_ROWS` linhas ou `DEFAULT_MAX_RESULT_SIZE_KB` KB sem confirmação explícita
- ✅ Recusa por linhas nunca busca o dataset completo antes de decidir

## 3. Contexto
**Depende de:** F2 (PostgreSQL Adapter) — 🟩 Done
**É dependência de:** F4 (Analysis Execution Engine)

## 4. Descrição Técnica

### 4.1 Componentes Afetados
```
├─ services/volume_guard_service.py (novo)
├─ schemas/exceptions.py (novo) — VolumeExceededError
├─ adapters/base.py (modificado) — assinatura abstrata de execute_query recebe `scalar: bool = False`
├─ adapters/postgresql.py (modificado) — implementação do parâmetro `scalar`
│    └─ scalar=True → conn.fetchval() (retorna int direto)
│    └─ scalar=False (padrão) → conn.fetch() (retorna list[dict], comportamento atual inalterado)
├─ config.py (modificado) — + DEFAULT_MAX_RESULT_ROWS, DEFAULT_MAX_RESULT_SIZE_KB
└─ .env / .env.example (modificado) — + as duas variáveis acima
```

> Nota de escopo: a geração do `count_sql` (envolvendo o SQL original em `SELECT COUNT(*) FROM (<sql_original>) AS sub`) é responsabilidade de quem **chama** o `VolumeGuardService` — na prática, isso será feito pelo `AnalysisService` em **F4**, já que é lá que o SQL original da análise é carregado de `analysis_steps`. F3 entrega o serviço pronto para receber esse `count_sql` já montado; não inclui a lógica de montagem do wrapper em si (fica documentado aqui para não ser esquecido na spec de F4).

### 4.2 Fluxo de Dados

```
1. (chamador, ex. F4) monta count_sql = f"SELECT COUNT(*) FROM ({sql_original}) AS sub"
2. VolumeGuardService.check_row_count(adapter, count_sql, params)
   ├─ adapter.execute_query(count_sql, params, scalar=True) → int
   ├─ count > DEFAULT_MAX_RESULT_ROWS → raise VolumeExceededError(estimated_rows=count)
   └─ count <= DEFAULT_MAX_RESULT_ROWS → return count
3. (chamador) executa a query completa (STEP 1, fora do escopo de F3) e serializa o resultado
4. VolumeGuardService.check_serialized_size(result: list[dict])
   ├─ size_kb = len(json.dumps(result).encode("utf-8")) / 1024
   ├─ size_kb > DEFAULT_MAX_RESULT_SIZE_KB → raise VolumeExceededError(estimated_size_kb=size_kb)
   └─ size_kb <= DEFAULT_MAX_RESULT_SIZE_KB → return size_kb
5. Se VolumeExceededError foi levantado em qualquer uma das checagens:
   VolumeGuardService.build_refinement_response(error) → dict estruturado (ver 4.4)
```

### 4.3 Banco de Dados
**Nenhuma alteração de schema.** Confirmado em ARQUITETURA.md §2.2: nenhuma migration é necessária para F3 além da remoção de `custom_handlers` (já feita na revisão v1.9).

### 4.4 Endpoints/Interfaces

```python
# schemas/exceptions.py
class VolumeExceededError(Exception):
    def __init__(self, estimated_rows: int | None = None, estimated_size_kb: float | None = None):
        self.estimated_rows = estimated_rows
        self.estimated_size_kb = estimated_size_kb
        super().__init__("Volume de resultado excede o limite configurado")


# services/volume_guard_service.py
class VolumeGuardService:
    def __init__(self, max_rows: int, max_size_kb: int):
        self.max_rows = max_rows          # DEFAULT_MAX_RESULT_ROWS (.env)
        self.max_size_kb = max_size_kb    # DEFAULT_MAX_RESULT_SIZE_KB (.env)

    async def check_row_count(self, adapter, count_sql: str, params: dict) -> int:
        """Executa COUNT(*) barato; levanta VolumeExceededError se exceder o limite."""
        count = await adapter.execute_query(count_sql, params, scalar=True)
        if count > self.max_rows:
            raise VolumeExceededError(estimated_rows=count)
        return count

    def check_serialized_size(self, result: list[dict]) -> float:
        """Mede o resultado já serializado em KB; levanta VolumeExceededError se exceder."""
        size_kb = len(json.dumps(result).encode("utf-8")) / 1024
        if size_kb > self.max_size_kb:
            raise VolumeExceededError(estimated_size_kb=size_kb)
        return size_kb

    def build_refinement_response(self, error: VolumeExceededError) -> dict:
        """Monta o payload estruturado de recusa (status volume_exceeded)."""
        return {
            "status": "volume_exceeded",
            "estimativa": {
                "linhas": error.estimated_rows,
                "tamanho_estimado_kb": error.estimated_size_kb,
            },
            "limite": {"linhas": self.max_rows, "tamanho_kb": self.max_size_kb},
            "mensagem": (
                f"Sua consulta retornaria aproximadamente {error.estimated_rows} linhas "
                f"(~{error.estimated_size_kb}KB), acima do limite de {self.max_rows} linhas / "
                f"{self.max_size_kb}KB. Refine o período ou adicione filtros (ex: região, produto). "
                f"Se quiser continuar mesmo assim, chame novamente com confirmar_volume_alto=true — "
                f"atenção: isso pode consumir um volume alto de tokens."
            ),
        }


# adapters/base.py (assinatura abstrata modificada)
class DatabaseAdapter(ABC):
    @abstractmethod
    async def execute_query(self, sql: str, params: dict | None = None, scalar: bool = False):
        """scalar=True retorna um único valor escalar (ex: COUNT(*)); scalar=False (padrão)
        retorna list[dict], uma linha por dict."""
        ...


# adapters/postgresql.py (implementação modificada)
class PostgreSQLAdapter(DatabaseAdapter):
    async def execute_query(self, sql: str, params: dict | None = None, scalar: bool = False):
        async with self.pool.acquire() as conn:
            if scalar:
                return await conn.fetchval(sql, *self._params_list(params))
            rows = await conn.fetch(sql, *self._params_list(params))
            return [dict(r) for r in rows]
```

## 5. Critérios de Aceitação
```gherkin
Feature: Controle de Volume de Resultado

Scenario: Volume dentro do limite
  Given uma análise cujo COUNT(*) estimado é 300 linhas
  And DEFAULT_MAX_RESULT_ROWS = 500
  When VolumeGuardService.check_row_count é chamado
  Then retorna 300 sem levantar exceção

Scenario: Volume de linhas excede o limite
  Given uma análise cujo COUNT(*) estimado é 8400 linhas
  And DEFAULT_MAX_RESULT_ROWS = 500
  When VolumeGuardService.check_row_count é chamado
  Then levanta VolumeExceededError(estimated_rows=8400)
  And o dataset completo NUNCA é buscado

Scenario: Contagem de linhas ok, mas tamanho serializado excede
  Given um resultado de 400 linhas com colunas muito largas, serializado em 510KB
  And DEFAULT_MAX_RESULT_SIZE_KB = 150
  When VolumeGuardService.check_serialized_size é chamado
  Then levanta VolumeExceededError(estimated_size_kb=510.0)

Scenario: Construção da resposta de recusa
  Given um VolumeExceededError com estimated_rows=8400
  When VolumeGuardService.build_refinement_response é chamado
  Then retorna dict com status "volume_exceeded", estimativa, limite e mensagem no formato especificado
```

## 6. Testes

### 6.1 Testes Unitários
```python
class TestVolumeGuardService:
    @pytest.mark.asyncio
    async def test_check_row_count_within_limit(self):
        adapter = AsyncMock()
        adapter.execute_query.return_value = 300
        service = VolumeGuardService(max_rows=500, max_size_kb=150)
        result = await service.check_row_count(adapter, "SELECT COUNT(*)...", {})
        assert result == 300

    @pytest.mark.asyncio
    async def test_check_row_count_exceeds_limit_raises(self):
        adapter = AsyncMock()
        adapter.execute_query.return_value = 8400
        service = VolumeGuardService(max_rows=500, max_size_kb=150)
        with pytest.raises(VolumeExceededError) as exc:
            await service.check_row_count(adapter, "SELECT COUNT(*)...", {})
        assert exc.value.estimated_rows == 8400

    def test_check_serialized_size_within_limit(self):
        service = VolumeGuardService(max_rows=500, max_size_kb=150)
        result = service.check_serialized_size([{"a": 1}] * 10)
        assert result < 150

    def test_check_serialized_size_exceeds_limit_raises(self):
        service = VolumeGuardService(max_rows=500, max_size_kb=1)
        big_result = [{"col": "x" * 1000}] * 100
        with pytest.raises(VolumeExceededError):
            service.check_serialized_size(big_result)

    def test_build_refinement_response_format(self):
        service = VolumeGuardService(max_rows=500, max_size_kb=150)
        error = VolumeExceededError(estimated_rows=8400, estimated_size_kb=510)
        response = service.build_refinement_response(error)
        assert response["status"] == "volume_exceeded"
        assert response["limite"] == {"linhas": 500, "tamanho_kb": 150}

class TestPostgreSQLAdapterScalar:
    @pytest.mark.asyncio
    async def test_execute_query_scalar_true_returns_int(self):
        # mock asyncpg connection.fetchval
        ...

    @pytest.mark.asyncio
    async def test_execute_query_scalar_false_returns_list_dict(self):
        # comportamento atual (F2) não pode regredir
        ...
```

### 6.2 Checklist de Testes
- [x] Teste unitário: caso de sucesso (linhas e KB dentro do limite)
- [x] Teste unitário: excede limite de linhas → recusa sem buscar dados completos
- [x] Teste unitário: excede limite de KB → recusa
- [x] Teste unitário: `build_refinement_response` gera payload correto
- [x] Teste unitário: `execute_query(scalar=True)` retorna int
- [x] Teste unitário: `execute_query(scalar=False)` mantém comportamento atual (regressão de F2)
- [ ] Manual: rodar `check_row_count` contra o Postgres de teste criado em F2, com uma tabela grande o suficiente para forçar a recusa

## 7. Mudanças na Configuração
**Variáveis de Environment (.env):**
```
DEFAULT_MAX_RESULT_ROWS=500
DEFAULT_MAX_RESULT_SIZE_KB=150
```

## 8. Documentação
### 8.1 Como a feature aparece no MCP
Não aparece diretamente ainda — F3 é um serviço interno. A resposta `volume_exceeded` só chega ao cliente MCP quando integrada em F4/F5.

### 8.2 Como o usuário usa essa feature
Indiretamente: ao pedir uma análise sem filtros suficientes, recebe a mensagem de refinamento em vez do dataset (via F4).

### 8.3 Como outros desenvolvedores estenderão isso
Qualquer chamador (hoje, apenas F4) monta o `count_sql` como subquery envolvendo o SQL original e chama `check_row_count` → executa a query completa → `check_serialized_size` → `build_refinement_response` se necessário.

## 9. Checklist de Implementação
**Código:**
- [x] `VolumeExceededError` em `schemas/exceptions.py`
- [x] `VolumeGuardService` completo em `services/volume_guard_service.py`
- [x] `DatabaseAdapter.execute_query` (abstract) com parâmetro `scalar`
- [x] `PostgreSQLAdapter.execute_query` implementando `scalar=True/False`
- [x] `config.py` com as duas novas settings
- [ ] Code review completo
- [x] Testes passing (100% dos casos)
- [x] Docstrings

**QA:**
- [ ] Code review aprovado
- [ ] PR merge aprovado
