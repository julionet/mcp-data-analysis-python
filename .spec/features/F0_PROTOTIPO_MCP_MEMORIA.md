# [F0] Protótipo MCP em Memória (Sprint 0)

## Feature Spec

**ID:** F0 (pré-Sprint 1 — não entra na numeração F1-F24 do FEATURES_ROADMAP.md)
**Nome:** Protótipo mínimo de servidor MCP via Streamable HTTP, dados em memória
**Prioridade:** 🔴 Crítica (bloqueia início confiável do Sprint 1)
**Esforço Estimado:** 0.5-1d
**Status:** ⬜ Todo

---

## 1. Visão

Validar, com o mínimo de código possível, que o núcleo da arquitetura proposta (ADR-006 do ARQUITETURA.md, v1.4) funciona antes de investir nas 24 features do Sprint 1-4: servidor MCP via Streamable HTTP, `list_tools`/`call_tool`, execução de uma análise fake e aplicação de 1 handler de transformação — tudo sem PostgreSQL, sem Handler Registry dinâmico, sem versionamento.

## 2. Objetivo

Confirmar que o SDK oficial MCP (`mcp`), usando a classe de baixo nível **`Server`** (não o wrapper `FastMCP`), funciona corretamente montado sobre FastAPI com transporte **Streamable HTTP** (via `StreamableHTTPSessionManager`), e que **Claude Desktop e ChatGPT Desktop** conseguem descobrir e executar uma "análise" fake apontando para `http://<ip>:3000/mcp`.

**Métrica de Sucesso:**
- ✅ Claude Desktop e ChatGPT Desktop listam a análise `vendas_por_regiao` via `list_tools()`
- ✅ Ambos executam `call_tool()` e recebem dados já transformados pelo handler
- ✅ `EXECUTION_LOG` em memória registra as chamadas de ambos (analysis_id, params, status)

## 3. Contexto

**Depende de:** — (é anterior ao F1 do FEATURES_ROADMAP.md)
**É dependência de:** F1 (FastAPI + MCP Server Setup via Streamable HTTP) — o protótipo valida a decisão que F1 vai formalizar em produção

**Ponto anteriormente em aberto — resolvido:** a lacuna de validação multi-cliente (registrada na versão anterior deste documento) fica resolvida: Jose vai testar com **Claude Desktop + ChatGPT Desktop**, dois clientes MCP de fabricantes diferentes, o que satisfaz de fato o espírito do critério F6 do FEATURES_ROADMAP.md (2+ clientes diferentes) — mesmo este F0 sendo só um protótipo, não a validação oficial do Sprint 1.

## 4. Descrição Técnica

### 4.1 Componentes Afetados (novos, protótipo isolado)
```
mcp_prototype/
├── main.py            # FastAPI app + mcp.server.lowlevel.Server + StreamableHTTPSessionManager
├── fake_data.py        # "análises", linhas fake e EXECUTION_LOG em memória
├── fake_handler.py      # 1 handler fake de transformação (substitui HandlerRegistry do F3)
└── requirements.txt
```

### 4.2 Fluxo de Dados

```
Claude Desktop / ChatGPT Desktop
   │ list_tools()
   ▼
main.py (mcp.server.lowlevel.Server)
   │ retorna Tool a partir de ANALYSES (fake_data.py)
   ▼
Claude Desktop / ChatGPT Desktop
   │ call_tool("vendas_por_regiao", {mes: "2026-09"})
   ▼
main.py
   ├─ 1. valida nome da análise em ANALYSES
   ├─ 2. busca FAKE_ROWS (substitui query real ao Postgres)
   ├─ 3. aplica fake_handler.apply(rows)  ← transformação, substitui HandlerRegistry
   ├─ 4. EXECUTION_LOG.append({...})       ← substitui execution_history (sem persistência)
   └─ 5. retorna resultado transformado (JSON)
   ▼
Cliente mostra resultado ao usuário (cada cliente independente, mesmo endpoint /mcp)
```

### 4.3 "Banco de Dados" (em memória — sem SQL, sem tabelas reais)

```python
# fake_data.py
ANALYSES = {
    "vendas_por_regiao": {
        "id": "vendas_por_regiao",
        "description": "Vendas agrupadas por região",
        "parameters": {"mes": "string"},
    }
}

FAKE_ROWS = [
    {"regiao": "Sudeste", "vendas": 15000},
    {"regiao": "Sul", "vendas": 8000},
    {"regiao": "Nordeste", "vendas": 6500},
]

EXECUTION_LOG: list[dict] = []  # substitui execution_history — perdido no restart
```

```python
# fake_handler.py — substitui HandlerRegistry/DataHandler do F3 (ARQUITETURA.md §4.3)
def apply(rows: list[dict]) -> list[dict]:
    """Handler fake: ordena por vendas desc e marca a maior região."""
    ordered = sorted(rows, key=lambda r: r["vendas"], reverse=True)
    if ordered:
        ordered[0]["destaque"] = True
    return ordered
```

### 4.4 Servidor MCP (SDK oficial, classe `Server` de baixo nível + Streamable HTTP)

```python
# main.py
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool, TextContent
import fake_data
import fake_handler

mcp_server = Server("analysis-prototype")

@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name=a["id"], description=a["description"], inputSchema={
            "type": "object",
            "properties": {"mes": {"type": "string"}},
        })
        for a in fake_data.ANALYSES.values()
    ]

@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name not in fake_data.ANALYSES:
        raise ValueError(f"Análise '{name}' não encontrada")

    result = fake_handler.apply(fake_data.FAKE_ROWS)
    fake_data.EXECUTION_LOG.append(
        {"analysis_id": name, "params": arguments, "status": "success"}
    )
    return [TextContent(type="text", text=str(result))]

session_manager = StreamableHTTPSessionManager(app=mcp_server)

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # FastAPI não propaga o lifespan de sub-apps montadas automaticamente —
    # o session_manager.run() precisa ser aberto/fechado manualmente aqui.
    async with session_manager.run():
        yield

app = FastAPI(lifespan=lifespan)
app.mount("/mcp", session_manager.handle_request)  # endpoint único: http://<ip>:3000/mcp
```

Executar com:
```bash
uvicorn main:app --host 0.0.0.0 --port 3000
```

> ⚠️ Nomes exatos de import (`mcp.server.lowlevel.Server`, `mcp.server.streamable_http_manager.StreamableHTTPSessionManager`, assinatura de `.handle_request`) variam entre versões do SDK `mcp` — confirmar contra a versão instalada antes de codar (`pip show mcp`), sem assumir. O requisito do lifespan manual é específico de montar sobre **FastAPI**; sobre Starlette puro o SDK cuida disso via `Mount`.

## 5. Critério de Aceitação

```gherkin
Feature: Protótipo MCP em memória com 2 clientes diferentes

Scenario: Descoberta da análise (Claude Desktop)
  Given o servidor roda em http://<ip>:3000
  And Claude Desktop está configurado com "url": "http://<ip>:3000/mcp"
  When Claude Desktop chama list_tools()
  Then a lista contém "vendas_por_regiao"

Scenario: Descoberta da análise (ChatGPT Desktop)
  Given o mesmo servidor em http://<ip>:3000
  And ChatGPT Desktop está configurado apontando para o mesmo endpoint "http://<ip>:3000/mcp"
  When ChatGPT Desktop chama list_tools()
  Then a lista contém "vendas_por_regiao" — igual ao que o Claude Desktop recebeu

Scenario: Execução com handler aplicado (qualquer um dos dois clientes)
  When o cliente chama call_tool("vendas_por_regiao", {"mes": "2026-09"})
  Then o resultado vem ordenado por vendas desc
  And o item de maior venda tem "destaque": true
  And EXECUTION_LOG ganha 1 entrada com status "success"

Scenario: Análise inexistente
  When o cliente chama call_tool("analise_fake", {})
  Then o erro retornado é claro (não stack trace), conforme RNF5/RF2 do NEGOCIO.md
```

## 6. Checklist de Teste (manual, com Claude Desktop + ChatGPT Desktop)

- [ ] Servidor sobe com `uvicorn main:app --port 3000`
- [ ] Claude Desktop configurado apontando para `http://<ip>:3000/mcp`, sem header/API Key (ADR-006)
- [ ] ChatGPT Desktop configurado apontando para o **mesmo** `http://<ip>:3000/mcp`, sem header/API Key
- [ ] `list_tools()` retorna a análise fake em ambos os clientes
- [ ] `call_tool()` retorna dados já transformados pelo handler em ambos os clientes
- [ ] Chamada com nome de análise inválido retorna erro tratado, não exception crua
- [ ] `EXECUTION_LOG` acumula entradas de ambos os clientes corretamente, sem erro de concorrência

## 7. Requisitos Atualizados (`requirements.txt`)

```
fastapi==0.104.1
uvicorn[standard]==0.24.0
mcp>=1.2.0          # SDK oficial — usa mcp.server.lowlevel.Server (baixo nível) + StreamableHTTPSessionManager, não FastMCP
```

> Sem `asyncpg`, `motor`, `aiomysql`, `aioodbc`, `redis`, `celery` — todos ficam para quando o F1 real (com Postgres) começar. Este protótipo não usa nenhuma dependência de banco de dados ou cache.

## 8. Fora do Escopo Deste Protótipo

- Persistência de qualquer tipo (banco, arquivo) — tudo em `dict`/`list` na memória do processo
- Handler Registry dinâmico (F3) — 1 handler hardcoded importado direto
- Cache (F7), versionamento (F9/F10), múltiplos adapters de BD (F11-F13)
- Teste de **concorrência** (chamadas simultâneas dos 2 clientes ao mesmo tempo) — este F0 valida que ambos funcionam contra o mesmo servidor, sequencialmente; concorrência real fica para o F6 oficial do Sprint 1

---

**Próximo passo:** rodar o checklist da seção 6 com Claude Desktop e ChatGPT Desktop apontando para `http://<ip>:3000/mcp`.
