"""Servidor MCP de baixo nível + transporte Streamable HTTP (ADR-006, ARQUITETURA.md §7).

F5: `list_tools()`/`call_tool()` delegam para mcp_transport/tools.py, que
gera as tools dinamicamente a partir de `analyses` (F5_MCP_TOOLS_INTEGRATION.md).

F12: o AuthMiddleware envolve os endpoints do /mcp (401 sem token válido) e grava
o usuário num contextvar; os handlers abaixo o leem e o repassam a tools.py.
"""

import contextlib
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool

from mcp_transport import tools
from schemas.auth import AuthenticatedUser
from security.auth_middleware import AuthMiddleware, current_user

mcp_server = Server(
    "analysis-mcp",
    instructions=(
        "Servidor de análises de dados de negócio. Cada análise ativa cadastrada "
        "em 'analyses' aparece como uma tool 'execute_<nome_da_analise>'."
    ),
)


def _require_user() -> AuthenticatedUser:
    """Usuário gravado pelo AuthMiddleware. Fail-closed: sem ele (middleware
    ausente/contornado) nenhuma tool é listada nem executada."""
    user = current_user.get()
    if user is None:
        raise PermissionError("Usuário autenticado ausente no contexto da requisição.")
    return user


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return await tools.list_tools(_require_user())


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    result = await tools.call_tool(name, arguments, _require_user())
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]


# stateless=True: cada requisição HTTP é independente (sem Mcp-Session-Id). Necessário
# para o F12 — token/usuário validados a cada chamada, bloqueio com efeito imediato.
session_manager = StreamableHTTPSessionManager(app=mcp_server, stateless=True)


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
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["WWW-Authenticate"],  # o 401 do AuthMiddleware; sem sessão (stateless) não há Mcp-Session-Id
    )
    async def authenticate(raw_token: str) -> AuthenticatedUser:
        # Resolvido a cada chamada (não um bound method capturado aqui), para os
        # testes poderem patchar tools.auth_service.authenticate depois do import.
        return await tools.auth_service.authenticate(raw_token)

    # O AuthMiddleware envolve os dois endpoints do /mcp (e só eles), por dentro do CORS.
    app.add_route("/mcp", AuthMiddleware(_MCPExactPathASGI(), authenticate))  # "/mcp" exato, sem redirect 307
    app.mount("/mcp", AuthMiddleware(session_manager.handle_request, authenticate))  # "/mcp/..." (qualquer sub-path)
