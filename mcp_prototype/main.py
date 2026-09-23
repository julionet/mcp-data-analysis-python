"""Protótipo F0 — servidor MCP via Streamable HTTP, dados em memória.

Valida ADR-006 (ARQUITETURA.md v1.4): SDK oficial `mcp`, classe de baixo nível
`Server`, montado sobre FastAPI com StreamableHTTPSessionManager, endpoint
único em /mcp, sem autenticação.
"""

import contextlib
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool

import fake_data
import fake_handler

mcp_server = Server(
    "analysis-prototype",
    instructions=(
        "Servidor de análises de dados de negócio. Cada ferramenta representa "
        "uma análise pré-configurada que consulta um banco de dados e retorna "
        "resultado já transformado. Use as ferramentas disponíveis sempre que "
        "o usuário pedir dados, números ou relatórios que correspondam à "
        "descrição de alguma delas — não é necessário pedir permissão."
    ),
)


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name=a["id"],
            description=a["description"],
            inputSchema={
                "type": "object",
                "properties": {
                    "mes": {
                        "type": "string",
                        "description": "Mês de referência da análise, no formato YYYY-MM (ex.: 2026-09).",
                    }
                },
            },
        )
        for a in fake_data.ANALYSES.values()
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name not in fake_data.ANALYSES:
        fake_data.EXECUTION_LOG.append(
            {"analysis_id": name, "params": arguments, "status": "error"}
        )
        raise ValueError(f"Análise '{name}' não encontrada")

    result = fake_handler.apply(fake_data.FAKE_ROWS)
    fake_data.EXECUTION_LOG.append(
        {"analysis_id": name, "params": arguments, "status": "success"}
    )
    return [TextContent(type="text", text=json.dumps(result))]


session_manager = StreamableHTTPSessionManager(app=mcp_server)


class _MCPExactPathASGI:
    """Encaminha para handle_request sem passar por Route(request)->Response.

    Necessário porque Starlette trata funções/métodos passados a `add_route`
    como `func(request) -> Response`; `handle_request` é ASGI puro
    `(scope, receive, send)`. Um objeto com `__call__` escapa dessa checagem.
    """

    async def __call__(self, scope, receive, send) -> None:
        await session_manager.handle_request(scope, receive, send)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # FastAPI não propaga o lifespan de sub-apps montadas automaticamente —
    # o session_manager.run() precisa ser aberto/fechado manualmente aqui.
    async with session_manager.run():
        yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # Clientes MCP desktop (Electron) podem validar o conector via fetch() no
    # processo de renderer, sujeito a CORS — sem isso, a checagem falha com um
    # erro genérico de "sem resposta", mesmo o servidor respondendo normalmente.
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)
app.add_route("/mcp", _MCPExactPathASGI())  # "/mcp" exato, sem redirect 307
app.mount("/mcp", session_manager.handle_request)  # "/mcp/..." (qualquer sub-path)


@app.get("/health")
async def health() -> JSONResponse:
    """Smoke test manual sem cliente MCP — não faz parte do protocolo."""
    return JSONResponse(
        {
            "status": "ok",
            "analyses": list(fake_data.ANALYSES.keys()),
            "execution_log_size": len(fake_data.EXECUTION_LOG),
        }
    )
