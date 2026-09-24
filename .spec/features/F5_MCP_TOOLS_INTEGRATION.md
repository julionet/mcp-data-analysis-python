# [F5] MCP Tools Integration (`list_tools` / `call_tool`)

## Feature Spec Template

**ID:** F5
**Nome:** MCP Tools Integration (`list_tools` / `call_tool`)
**Prioridade:** 🔴 Crítica
**Esforço Estimado:** 1d (8h)
**Status:** 🟩 Done

---

## 1. Visão

Expõe cada análise cadastrada e ativa em `analyses` como uma tool MCP dinâmica (`execute_<nome_da_analise>`), e implementa o único ponto de entrada de execução (`call_tool`) que resolve qual análise executar a partir do nome recebido do protocolo. É a peça que entrega, na prática, a promessa central do produto (NEGOCIO.md O1/RF1): cadastrar uma análise no banco e ela aparecer automaticamente em qualquer cliente MCP conectado, sem nenhum código novo.

## 2. Objetivo

Fazer o servidor MCP (via Streamable HTTP, já de pé desde F1) responder corretamente aos dois métodos padrão do protocolo — `list_tools()` e `call_tool()` — usando exclusivamente os dados já existentes em `analyses`/`analysis_steps` (F2) e o motor de execução já implementado (F4), sem nenhum handler ou lógica hardcoded por análise.

**Métrica de Sucesso:**
- ✅ Uma análise nova cadastrada via `INSERT` em `analyses` aparece na próxima chamada de `list_tools()`, sem restart do servidor e sem alteração de código
- ✅ `call_tool()` nunca propaga exceção para o cliente MCP — todo caminho de saída é um dict estruturado (`success` / `volume_exceeded` / `error`)
- ✅ Uma análise com `analyses.name` fora do padrão de identificador MCP é logada como warning e **não** aparece em `list_tools()`, em vez de gerar uma tool inválida

## 3. Contexto

**Depende de:** F1 (FastAPI + MCP Server Setup), F4 (Analysis Execution Engine)
**É dependência de:** F6 (Validação Multi-Cliente Simultâneo)

**Fora de escopo desta feature:** `list_resources()` / `read_resource()` — avaliados durante a elaboração desta spec e descartados por falta de requisito de negócio que os justifique (nenhum RF/UC em NEGOCIO.md os exige; `list_tools()` + `call_tool()` já cobrem 100% do fluxo). Ficam anotados apenas como "endpoints padrão MCP disponíveis, não utilizados em V1.0" (ver ARQUITETURA.md §2.1) — se surgir um requisito real no futuro, entram como feature nova.

## 4. Descrição Técnica

### 4.1 Componentes Afetados

```
Componentes que serão criados/modificados:
├─ mcp_transport/tools.py (novo) — list_tools() e call_tool()
├─ repositories/analysis_repo.py (modificado) — novo método get_by_name()
├─ services/analysis_service.py (modificado — AJUSTE RETROATIVO)
│    └─ execute() deixa de propagar exceção; passa a devolver SEMPRE um dict
│       {"status": "success"|"volume_exceeded"|"error", ...}
├─ services/volume_guard_service.py (sem mudança de comportamento — apenas
│    consumido internamente por analysis_service.py, que agora captura o
│    VolumeExceededError e chama build_refinement_response() por dentro)
└─ main.py (modificado) — registro dos handlers list_tools/call_tool no
     servidor Streamable HTTP montado em F1
```

### 4.2 Fluxo de Dados

**Fluxo A — Descoberta (`list_tools`)**

```
1. Cliente MCP chama list_tools()
2. AnalysisService.get_all_analyses() → SELECT * FROM analyses WHERE is_active = true
3. Para cada análise retornada:
   a. Valida analyses.name contra padrão de identificador (^[a-z][a-z0-9_]*$)
      ├─ inválido → loga warning, PULA essa análise (não entra na lista)
      └─ válido → segue
   b. Gera inputSchema via schemas/analysis_parameters.py::to_json_schema(analyses.parameters)
   c. Injeta a propriedade reservada "confirmar_volume_alto" (boolean, default false)
      no inputSchema — não vem de analyses.parameters, é global e fixa
   d. Monta Tool: name = f"execute_{analyses.name}", description = analyses.description,
      inputSchema = schema montado em (b)+(c)
4. Retorna a lista de Tools ao cliente MCP
```

**Fluxo B — Execução (`call_tool`)**

```
1. Cliente MCP chama call_tool(name="execute_<nome>", arguments={...})
2. call_tool() extrai analysis_name = name.removeprefix("execute_")
3. analysis = AnalysisRepository.get_by_name(analysis_name)
   └─ consulta o banco a cada chamada (SEM cache em memória do mapa nome→id,
      para manter a mesma garantia de "sempre fresh" do list_tools() — RF1)
4. Se analysis is None OU analysis.is_active == false:
   └─ retorna {"status": "error", "mensagem": "Análise '<nome>' não encontrada ou inativa."}
5. confirmar_volume_alto = arguments.pop("confirmar_volume_alto", False)
6. result = AnalysisService.execute(analysis.id, arguments, confirmar_volume_alto)
   └─ (chamada única — TODAS as tools passam por este mesmo método;
       o "name" recebido do protocolo é o dado que resolve qual análise é)
7. Dentro de AnalysisService.execute() (ajuste retroativo desta feature):
   ├─ try:
   │    VolumeGuardService.check_row_count(...)  (COUNT(*) pré-check)
   │    dataset = executa STEP 1 (query real via Adapter)
   │    VolumeGuardService.check_serialized_size(dataset)
   │    return {"status": "success", "data": dataset}
   ├─ except VolumeExceededError as e:
   │    return VolumeGuardService.build_refinement_response(e)
   └─ except Exception as e:
        loga stack trace completo (nível ERROR)
        return {"status": "error", "mensagem": "<mensagem amigável, sem stack trace>"}
8. call_tool() repassa o dict de execute() como resultado da tool (sem try/except
   próprio — a garantia de "nunca propagar exceção" já é responsabilidade do
   AnalysisService.execute() a partir desta feature)
9. Cliente MCP recebe o dict (dentro de um TextContent serializado em JSON) e
   decide como apresentar ao usuário — sucesso, pedido de refinamento, ou erro
```

### 4.3 Banco de Dados

Nenhuma tabela nova nem alteração de schema nesta feature. Nenhuma migration necessária.

### 4.4 Endpoints/Interfaces

```python
# repositories/analysis_repo.py

async def get_by_name(self, name: str) -> Optional[Analysis]:
    """Busca uma análise ativa ou inativa pelo nome único (analyses.name).
    Usada por call_tool() a cada execução — sem cache, para refletir
    imediatamente qualquer mudança feita no banco (ativação/desativação/rename).
    """
    ...
```

```python
# services/analysis_service.py — AJUSTE RETROATIVO (F4 → revisado nesta feature)

async def execute(
    self,
    analysis_id: UUID,
    params: dict,
    confirmar_volume_alto: bool = False,
) -> dict:
    """Executa uma análise e SEMPRE retorna um dict estruturado — nunca
    propaga exceção. Formatos possíveis de retorno:
      {"status": "success", "data": [...]}
      {"status": "volume_exceeded", "estimativa": {...}, "limite": {...}, "mensagem": "..."}
      {"status": "error", "mensagem": "..."}
    """
    ...
```

```python
# mcp_transport/tools.py

async def list_tools() -> list[Tool]:
    """Gera dinamicamente uma Tool MCP por análise ativa e com nome válido."""
    ...

async def call_tool(name: str, arguments: dict) -> dict:
    """Único ponto de entrada de execução de análises via MCP. Resolve a
    análise pelo nome recebido do protocolo e repassa o resultado (já
    estruturado por AnalysisService.execute()) ao cliente MCP.
    """
    ...
```

## 5. Critérios de Aceitação

```gherkin
Feature: MCP Tools Integration

Scenario: Descoberta lista apenas análises ativas e com nome válido
  Given existem 3 análises ativas com nomes válidos e 1 análise inativa no banco
  When um cliente MCP chama list_tools()
  Then a resposta contém exatamente 3 tools
  And cada tool tem o nome no formato "execute_<nome_da_analise>"
  And cada inputSchema inclui a propriedade "confirmar_volume_alto"

Scenario: Análise com nome inválido é ignorada na descoberta
  Given existe uma análise ativa cujo campo "name" contém espaços ou maiúsculas
  When um cliente MCP chama list_tools()
  Then essa análise NÃO aparece na lista de tools
  And um warning é registrado no log

Scenario: Execução com sucesso
  Given a análise "vendas_por_regiao" está ativa e dentro do limite de volume
  When o cliente MCP chama call_tool("execute_vendas_por_regiao", {"data_inicial": "...", "data_final": "..."})
  Then o retorno é {"status": "success", "data": [...]}

Scenario: Execução recusada por volume alto
  Given a mesma análise, mas os filtros informados excedem DEFAULT_MAX_RESULT_ROWS
  When o cliente MCP chama call_tool(..., confirmar_volume_alto=false)
  Then o retorno é {"status": "volume_exceeded", "estimativa": {...}, "limite": {...}, "mensagem": "..."}
  And nenhuma query completa (fora o COUNT(*)) foi executada

Scenario: Execução confirmada explicitamente com volume alto
  Given o mesmo cenário acima
  When o cliente MCP chama call_tool(..., confirmar_volume_alto=true)
  Then o retorno é {"status": "success", "data": [...], "aviso": "resultado grande, enviado por confirmação explícita"}

Scenario: Tool chamada para análise inexistente ou inativa
  When o cliente MCP chama call_tool("execute_analise_que_nao_existe", {})
  Then o retorno é {"status": "error", "mensagem": "..."}
  And nenhuma exceção é propagada ao transporte MCP

Scenario: Erro interno durante a execução (ex.: falha de conexão com o data source)
  Given o adapter do data source lança uma exceção ao executar a query
  When o cliente MCP chama call_tool("execute_vendas_por_regiao", {...})
  Then o retorno é {"status": "error", "mensagem": "<mensagem amigável>"}
  And o stack trace completo é registrado no log do servidor (nível ERROR)
  And nenhuma exceção é propagada ao transporte MCP
```

## 6. Testes

### 6.1 Testes Unitários

```python
class TestMcpTools:
    @pytest.mark.asyncio
    async def test_list_tools_returns_one_tool_per_active_analysis(self):
        ...

    @pytest.mark.asyncio
    async def test_list_tools_skips_analysis_with_invalid_name(self):
        ...

    @pytest.mark.asyncio
    async def test_list_tools_injects_confirmar_volume_alto_in_every_schema(self):
        ...

    @pytest.mark.asyncio
    async def test_call_tool_success_returns_status_success(self):
        ...

    @pytest.mark.asyncio
    async def test_call_tool_analysis_not_found_returns_status_error(self):
        ...

    @pytest.mark.asyncio
    async def test_call_tool_inactive_analysis_returns_status_error(self):
        ...

    @pytest.mark.asyncio
    async def test_call_tool_never_raises_on_internal_exception(self):
        ...


class TestAnalysisServiceExecuteContract:
    @pytest.mark.asyncio
    async def test_execute_success_returns_dict_with_data(self):
        ...

    @pytest.mark.asyncio
    async def test_execute_volume_exceeded_returns_status_volume_exceeded_dict(self):
        ...

    @pytest.mark.asyncio
    async def test_execute_confirmar_volume_alto_bypasses_limit_and_adds_aviso(self):
        ...

    @pytest.mark.asyncio
    async def test_execute_internal_error_returns_error_dict_never_raises(self):
        ...
```

### 6.2 Checklist de Testes
- [x] Teste unitário: `list_tools()` gera uma tool por análise ativa
- [x] Teste unitário: `list_tools()` pula análise com nome inválido (loga warning)
- [x] Teste unitário: `inputSchema` inclui `confirmar_volume_alto` em toda tool
- [x] Teste unitário: `call_tool()` — sucesso
- [x] Teste unitário: `call_tool()` — análise inexistente/inativa
- [x] Teste unitário: `call_tool()` — nunca propaga exceção
- [x] Teste unitário: `AnalysisService.execute()` — contrato de retorno nos 3 status (success/volume_exceeded/error)
- [x] Teste de integração: fluxo completo `list_tools()` → `call_tool()` → resultado, contra banco de teste real (smoke test manual contra o Config DB real — sem analyses cadastradas ainda no ambiente local; ver §9 nota)
- [ ] Manual: testar via pelo menos 1 cliente MCP real (Claude Desktop, conforme já validado no protótipo F0) — pendente, requer análise real cadastrada (`scripts/seed_analise_vendas.py` bloqueado localmente por `FERNET_KEY` mal configurada no `.env`, fora do escopo desta feature)

## 7. Mudanças na Configuração

**Variáveis de Environment (.env):**
```
# Nenhuma variável nova nesta feature.
# DEFAULT_MAX_RESULT_ROWS e DEFAULT_MAX_RESULT_SIZE_KB já existem desde F3.
```

## 8. Documentação

### 8.1 Como a feature aparece no MCP
Cada análise ativa e com nome válido em `analyses` se torna uma tool chamada `execute_<nome_da_analise>`, com `inputSchema` derivado de `analyses.parameters` mais a propriedade global `confirmar_volume_alto`. A lista é sempre recalculada a partir do banco — não há cache de descoberta.

### 8.2 Como o usuário usa essa feature
Nenhuma ação manual: ao cadastrar uma análise ativa via `INSERT` em `analyses`/`analysis_steps` (fluxo já documentado em UC1 do NEGOCIO.md), ela passa a aparecer automaticamente na próxima vez que o cliente MCP consultar a lista de tools — sem restart do servidor.

### 8.3 Como outros desenvolvedores estenderão isso
Não há extensão de código por análise. Qualquer ajuste de comportamento (novo tipo de parâmetro, novo status de retorno) deve ser feito nos módulos compartilhados (`schemas/analysis_parameters.py`, `services/analysis_service.py`), nunca em `mcp_transport/tools.py`, que deve permanecer agnóstico de qual análise está sendo processada.

## 9. Checklist de Implementação

**Código:**
- [x] `repositories/analysis_repo.py::get_by_name()` implementado
- [x] `services/analysis_service.py::execute()` ajustado para nunca propagar exceção (ajuste retroativo)
- [x] `mcp_transport/tools.py::list_tools()` implementado
- [x] `mcp_transport/tools.py::call_tool()` implementado
- [x] Validação de nome de análise (regex) no `list_tools()`, com log de warning para nomes inválidos
- [x] Handlers registrados em `mcp_transport/__init__.py`, no servidor Streamable HTTP montado por `main.py` (F1) — `list_tools()`/`call_tool()` do `Server` MCP passam a delegar para `mcp_transport/tools.py`
- [ ] Code review completo
- [x] Testes passing (100% dos casos — 1 falha pré-existente e não relacionada em `test_crypto.py`, causada por `FERNET_KEY` duplicada no `.env` local)
- [x] Docstrings

**QA:**
- [ ] Code review aprovado
- [ ] PR merge aprovado

## 10. Nota de Implementação (2026-09-24)

- Status do payload de recusa por volume renomeado de `refinamento_necessario` (usado em ARQUITETURA.md v1.9 e F3/F4) para **`volume_exceeded`**, para bater com o texto já escrito nesta spec (§4.2, §5, §6.1) — decisão confirmada com o usuário, aplicada retroativamente em ARQUITETURA.md (agora v1.10), F3_CONTROLE_VOLUME.md, F4_EXECUTION_ENGINE.md, FEATURES_ROADMAP.md e nos testes/código de F3/F4.
- `confirmar_volume_alto=true` agora bypassa os dois checks (`check_row_count` e `check_serialized_size`) em vez de apenas ser aceito e ignorado — nenhum `COUNT(*)` é executado nesse caminho, e o payload de sucesso ganha `"aviso": "resultado grande, enviado por confirmação explícita"`.
- Teste manual com cliente MCP real (Claude Desktop) não foi executado nesta sessão — o ambiente local não tem nenhuma análise cadastrada (`analyses` vazia) e o script de seed (`scripts/seed_analise_vendas.py`) está bloqueado por um `FERNET_KEY` mal formatada no `.env` (`FERNET_KEY=FERNET_KEY=...`, duplicada), pré-existente e fora do escopo desta feature. O fluxo foi validado via testes unitários (mocks) e um smoke test manual de `list_tools()`/`call_tool()` contra o Config DB real (sem analyses cadastradas + análise inexistente), confirmando que nenhuma exceção escapa para o transporte MCP.
