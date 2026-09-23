"""Servidor MCP de baixo nível + transporte Streamable HTTP (ADR-006, ARQUITETURA.md §7).

F1: apenas o transporte. `list_tools()`/`call_tool()` ficam como stub —
a lógica real (AnalysisService, HandlerRegistry) entra em F5.
"""

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool

mcp_server = Server(
    "analysis-mcp",
    instructions=(
        "Servidor de análises de dados de negócio. Nenhuma análise cadastrada "
        "ainda nesta etapa (F1) — apenas o transporte está disponível."
    ),
)


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return []  # stub nesta feature — análises reais entram em F5


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    raise NotImplementedError("Nenhuma análise cadastrada ainda — ver F5")


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


def configure_mcp(app: FastAPI) -> None:
    """Monta CORS, a rota exata /mcp e o mount /mcp/... no app FastAPI."""
    app.add_middleware(
        CORSMiddleware,
        # Clientes MCP desktop (Electron) podem validar o conector via fetch() no
        # processo de renderer, sujeito a CORS — sem isso, a checagem falha com um
        # erro genérico de "sem resposta", mesmo o servidor respondendo normalmente.
        allow_origins=["*"],  # confirmado: rede interna, todas origens liberadas
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )
    app.add_route("/mcp", _MCPExactPathASGI())  # "/mcp" exato, sem redirect 307
    app.mount("/mcp", session_manager.handle_request)  # "/mcp/..." (qualquer sub-path)
