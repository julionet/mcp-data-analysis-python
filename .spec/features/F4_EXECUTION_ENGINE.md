# [F4] Analysis Execution Engine

## Feature Spec Template

**ID:** F4
**Nome:** Analysis Execution Engine
**Prioridade:** 🔴 Crítica
**Esforço Estimado:** 2d (16h)
**Status:** 🟩 Done

> **Ajuste retroativo (F5, 2026-09-24):** `AnalysisService.execute()` ganhou o parâmetro `confirmar_volume_alto` (bypass real dos checks de volume) e deixou de propagar exceção — todo retorno é um dict `{"status": "success"|"volume_exceeded"|"error", ...}`. Ver F5_MCP_TOOLS_INTEGRATION.md §4.2/§4.4/§10.

---

## 1. Visão
O Analysis Execution Engine é o núcleo do fluxo "pedir análise → receber dado real": carrega a definição de uma análise cadastrada no Config DB, valida seus parâmetros, seleciona o adapter certo para o data source, aplica o Controle de Volume (F3) e executa a query, devolvendo o dataset bruto. É o `AnalysisService.execute()`, a peça que amarra tudo que foi construído em F1-F3 antes de expor via MCP (F5).

## 2. Objetivo
Permitir executar uma análise cadastrada manualmente no banco, ponta a ponta (do ID da análise até o dataset retornado), com validação de parâmetros e proteção contra volume alto de dados — sem cache, sem log de auditoria e sem exposição MCP (etapas futuras: F5, F7, F8).

**Métrica de Sucesso:**
- ✅ Dado o ID de uma análise cadastrada manualmente (ex.: `vendas_por_periodo`) e parâmetros válidos, `execute()` retorna o dataset bruto correto
- ✅ Parâmetros inválidos (tipo errado, campo obrigatório faltando) são rejeitados com mensagem clara, sem chegar a tocar no banco de dados
- ✅ Uma análise com schema mal formado (ex.: `type` inválido) é rejeitada por `validate_schema()` antes de tentar gerar o Pydantic model
- ✅ Volume acima do limite (F3) interrompe a execução antes de buscar o dataset completo
- ✅ Erro de conexão/SQL no data source é reportado sem stack trace

## 3. Contexto
**Depende de:** F2 (PostgreSQL Adapter), F3 (Controle de Volume de Resultado)
**É dependência de:** F5 (MCP Tools Integration), F7 (Cache Service), F8 (Log de Execução)

## 4. Descrição Técnica

### 4.1 Componentes Afetados
```
Componentes que serão criados/modificados:
├─ services/analysis_service.py         (novo) — AnalysisService.execute(), get_all_analyses()
├─ repositories/analysis_repo.py        (novo) — AnalysisRepository (get_by_id, get_all, get_steps)
├─ repositories/data_source_repo.py     (novo) — DataSourceRepository (get_by_id)
├─ schemas/analysis_parameters.py       (novo) — validate_schema(), to_pydantic_model(), to_json_schema()
├─ adapters/factory.py                  (novo) — AdapterFactory (só 'postgresql' registrado)
├─ security/crypto.py                   (novo) — decrypt_password() / encrypt_password() via Fernet
├─ core/exceptions.py                   (modificado, já existe desde F3) — novas exceptions
└─ scripts/seed_analise_vendas.py       (já entregue) — cadastro manual de análise de teste
```

### 4.2 Fluxo de Dados

Recortado de ARQUITETURA.md §3.2, mantendo só o que pertence ao F4 (sem cache/log/MCP):

```
AnalysisService.execute(analysis_id: UUID, params: dict) -> dict
│
├─ 1. AnalysisRepository.get_by_id(analysis_id)
│      └─ não encontrada ou is_active=false → AnalysisNotFoundError
│
├─ 2. validate_schema(analysis.parameters)
│      └─ schema mal formado (type inválido, enum incompatível, min/max fora
│         de number/integer, etc.) → InvalidAnalysisSchemaError
│         (erro de configuração — quem cadastrou a análise errou, não o cliente)
│
├─ 3. to_pydantic_model(analysis.parameters) → ParamsModel
│      └─ ParamsModel(**params) valida os valores recebidos do cliente
│         → inválido → InvalidParametersError (mensagem clara, sem stack trace)
│
├─ 4. DataSourceRepository.get_by_id(analysis.data_source_id)
│      └─ decrypt_password(connection_config.password)  [Fernet, FERNET_KEY do .env]
│
├─ 5. AdapterFactory.create_adapter(data_source.type, connection_config)
│      └─ tipo não registrado (ex.: 'mongodb' ainda não implementado) → ValueError claro
│
├─ 6. AnalysisRepository.get_steps(analysis_id) → analysis_steps (step_order=1, type='query')
│      └─ traduz SQL nomeado (":data_inicial", ":pago", ...) para posicional
│         ($1, $2, ...) na ordem de definition["params"]
│
├─ 7. VolumeGuardService.check_row_count(adapter, count_sql, valores_ordenados)
│      └─ excede DEFAULT_MAX_RESULT_ROWS → devolve volume_exceeded, PARA aqui
│
├─ 8. adapter.execute_query(sql_traduzido, valores_ordenados) → dataset bruto
│      └─ erro de conexão/SQL → DataSourceConnectionError (mensagem clara)
│
├─ 9. VolumeGuardService.check_serialized_size(dataset)
│      └─ excede DEFAULT_MAX_RESULT_SIZE_KB → devolve volume_exceeded
│
└─ 10. return {"status": "success", "data": dataset}
```

**Decisão registrada nesta feature — tradução de parâmetros nomeados:**
O SQL em `analysis_steps.definition.sql` usa placeholders nomeados (`:data_inicial`, `:pago`, ...). O `AnalysisService` traduz para os placeholders posicionais que o `asyncpg` exige (`$1`, `$2`, ...), na ordem declarada em `definition["params"]`, imediatamente antes de chamar `adapter.execute_query()`. Essa tradução não estava formalizada em nenhum documento anterior — é uma decisão de implementação necessária para o F4 funcionar, criada e aprovada nesta feature.

### 4.3 Banco de Dados
Nenhuma tabela nova ou alteração de schema — o F4 só lê as tabelas já criadas no F2 (`data_sources`, `analyses`, `analysis_steps`).

**Dados de teste** (via `scripts/seed_analise_vendas.py`, já entregue):
- 1 `data_sources`: `vendas_db_local` (postgresql → `localhost/data_db`, usuário `chronus`, senha cifrada com Fernet, `sslmode: "disable"` — conexão local sem TLS configurado no Postgres de origem)
- 1 `analyses`: `vendas_por_periodo` (`data_inicial`, `data_final` obrigatórios; `pago` opcional)
- 1 `analysis_steps`: query sobre a tabela `vendas` (`data`, `valor`, `pago`)

### 4.4 Endpoints/Interfaces

```python
# schemas/analysis_parameters.py

def validate_schema(parameters: dict) -> None:
    """Valida a ESTRUTURA do JSON de analyses.parameters (§2.3) — não os
    valores enviados pelo cliente. Levanta InvalidAnalysisSchemaError se:
    - 'type' fora de {string, integer, number, boolean, date, datetime}
    - 'required' não é bool
    - 'enum' presente mas incompatível com o 'type'
    - 'min'/'max' presentes fora de number/integer
    Chamada ANTES de to_pydantic_model(), pois cadastro de análises em V1.0
    é 100% manual via INSERT — sem UI de validação no cadastro."""
    ...

def to_pydantic_model(parameters: dict) -> Type[BaseModel]:
    """Gera dinamicamente um modelo Pydantic a partir de analyses.parameters,
    para validar os VALORES recebidos do cliente. Assume que validate_schema()
    já rodou (não revalida a estrutura do schema)."""
    ...

def to_json_schema(parameters: dict) -> dict:
    """Converte analyses.parameters para JSON Schema padrão MCP.
    Implementado nesta feature; consumido pelo F5 (list_tools)."""
    ...
```

```python
# services/analysis_service.py

class AnalysisService:
    def __init__(
        self,
        analysis_repo: AnalysisRepository,
        data_source_repo: DataSourceRepository,
        volume_guard: VolumeGuardService,
    ):
        ...

    async def execute(self, analysis_id: UUID, params: dict) -> dict:
        """Executa uma análise cadastrada — ver fluxo completo em §4.2.
        Retorna {"status": "success", "data": [...]} ou
        {"status": "volume_exceeded", ...} (ver ARQUITETURA.md §3.4)."""
        ...

    async def get_all_analyses(self) -> list[Analysis]:
        """Lista análises ativas. Sem endpoint MCP nesta feature (isso é F5) —
        método já disponível no Service para o F5 consumir depois."""
        ...
```

```python
# adapters/factory.py

class AdapterFactory:
    _adapters: dict[str, Type[DatabaseAdapter]] = {
        "postgresql": PostgreSQLAdapter,
        # demais tipos entram no Sprint 2 (F11 MongoDB, F12 MySQL, F13 SQL Server)
    }

    @classmethod
    def create_adapter(cls, source_type: str, config: dict) -> DatabaseAdapter:
        """Levanta ValueError com mensagem clara se source_type não estiver
        registrado (ex.: 'mongodb' antes do F11)."""
        ...
```

```python
# security/crypto.py

def decrypt_password(encrypted: str) -> str:
    """Descriptografa connection_config.password usando Fernet
    (FERNET_KEY do .env). Ver ARQUITETURA.md §8.2."""
    ...

def encrypt_password(plain: str) -> str:
    """Usado por scripts de cadastro manual (ex.: seed_analise_vendas.py)."""
    ...
```

## 5. Critérios de Aceitação
```gherkin
Feature: Analysis Execution Engine

Scenario: Execução com sucesso (Postgres, dentro do limite de volume)
  Given a análise "vendas_por_periodo" está cadastrada e ativa
  And o data source aponta para data_db/vendas com senha cifrada
  When AnalysisService.execute() é chamado com data_inicial e data_final válidos
  Then o resultado retorna status "success"
  And os dados retornados batem com o que existe na tabela vendas para o período

Scenario: Parâmetros inválidos
  Given a análise "vendas_por_periodo" está cadastrada
  When execute() é chamado sem o campo obrigatório "data_inicial"
  Then InvalidParametersError é levantado
  And a mensagem indica claramente qual campo está faltando/incorreto

Scenario: Schema de análise mal formado
  Given uma análise cadastrada manualmente com um parâmetro type="foo" (inválido)
  When execute() é chamado
  Then validate_schema() levanta InvalidAnalysisSchemaError
  And to_pydantic_model() nunca é chamado

Scenario: Análise inexistente ou inativa
  Given nenhuma análise com o ID informado existe (ou is_active=false)
  When execute() é chamado
  Then AnalysisNotFoundError é levantado

Scenario: Volume de dados excedido (linhas)
  Given os filtros informados retornariam mais linhas que DEFAULT_MAX_RESULT_ROWS
  When execute() é chamado
  Then o resultado é {"status": "volume_exceeded", ...}
  And a query completa (sem COUNT) nunca é executada

Scenario: Erro de conexão com o data source
  Given o Postgres do data source está inacessível
  When execute() é chamado
  Then DataSourceConnectionError é levantado
  And a mensagem não expõe stack trace nem credenciais
```

## 6. Testes

### 6.1 Testes Unitários
```python
class TestAnalysisService:
    @pytest.mark.asyncio
    async def test_execute_success_returns_raw_dataset(self):
        ...

    @pytest.mark.asyncio
    async def test_execute_analysis_not_found(self):
        ...

    @pytest.mark.asyncio
    async def test_execute_invalid_params_raises_clear_error(self):
        ...

    @pytest.mark.asyncio
    async def test_execute_stops_before_full_query_on_volume_exceeded(self):
        ...

    @pytest.mark.asyncio
    async def test_execute_wraps_connection_error_without_stacktrace(self):
        ...


class TestAnalysisParametersSchema:
    def test_validate_schema_rejects_invalid_type(self):
        ...

    def test_validate_schema_accepts_valid_schema(self):
        ...

    def test_to_pydantic_model_builds_correct_types(self):
        ...

    def test_to_pydantic_model_enforces_required_fields(self):
        ...

    def test_to_json_schema_matches_mcp_input_schema_format(self):
        ...


class TestAdapterFactory:
    def test_create_adapter_postgresql(self):
        ...

    def test_create_adapter_unknown_type_raises(self):
        ...


class TestCryptoUtils:
    def test_decrypt_password_roundtrip(self):
        ...
```

### 6.2 Checklist de Testes
- [x] Teste unitário: execução com sucesso (dataset bruto correto)
- [x] Teste unitário: análise não encontrada / inativa
- [x] Teste unitário: schema de análise mal formado (validate_schema)
- [x] Teste unitário: parâmetros inválidos (to_pydantic_model)
- [x] Teste unitário: tradução de params nomeados → posicional
- [x] Teste unitário: AdapterFactory (tipo válido e tipo desconhecido)
- [x] Teste unitário: decrypt_password / encrypt_password (roundtrip)
- [x] Teste unitário: volume excedido interrompe antes da query completa (integração com F3)
- [ ] Teste de integração: fluxo completo contra o Postgres real (data_db/vendas) usando o seed
- [ ] Manual: rodar seed_analise_vendas.py, cadastrar no Config DB, chamar execute() diretamente (sem MCP ainda) e confirmar dataset

## 7. Mudanças na Configuração
**Variáveis de Environment (.env):**
```
FERNET_KEY=<já existente desde F1/F3 — reutilizada aqui para decrypt_password()>
```
Nenhuma variável nova — `FERNET_KEY` já estava prevista desde §5.1/§8.2 do ARQUITETURA.md; nesta feature passa a ser efetivamente usada.

## 8. Documentação
### 8.1 Como a feature aparece no MCP
Ainda não aparece — `AnalysisService.execute()` é chamável apenas internamente/via teste manual nesta feature. Exposição via `list_tools()`/`call_tool()` é o F5.

### 8.2 Como o usuário usa essa feature
Nesta etapa não há uso via cliente MCP. Jose valida manualmente chamando `AnalysisService.execute(analysis_id, params)` num script/teste, após rodar `seed_analise_vendas.py` para ter uma análise cadastrada no Config DB.

### 8.3 Como outros desenvolvedores estenderão isso
- Novo tipo de data source → registrar no `AdapterFactory._adapters` (1 linha) + implementar `DatabaseAdapter` (F11-F13 já previstos no roadmap)
- Novo tipo de parâmetro → estender `validate_schema()` e `to_pydantic_model()`/`to_json_schema()` no mapeamento de tipos (§2.3 do ARQUITETURA.md)
- Nova análise → INSERT manual em `analyses`/`analysis_steps` (zero código), seguindo o padrão do `seed_analise_vendas.py`

## 9. Checklist de Implementação
**Código:**
- [x] AnalysisRepository + DataSourceRepository implementados
- [x] AdapterFactory implementado (postgresql apenas)
- [x] schemas/analysis_parameters.py (validate_schema, to_pydantic_model, to_json_schema)
- [x] security/crypto.py (decrypt_password, encrypt_password)
- [x] AnalysisService.execute() + get_all_analyses()
- [x] Tradução de params nomeados (":nome") → posicional ($1, $2, ...)
- [x] Novas exceptions: AnalysisNotFoundError, InvalidParametersError, InvalidAnalysisSchemaError, DataSourceConnectionError
- [ ] Code review completo
- [x] Testes passing (100% dos casos unitários do §6.2 — integração/manual pendentes)
- [x] Docstrings

**QA:**
- [ ] Code review aprovado
- [ ] Seed rodado e análise testada manualmente contra data_db/vendas
- [ ] PR merge aprovado
