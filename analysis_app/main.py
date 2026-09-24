"""Entry point FastAPI — monta o transporte MCP (Streamable HTTP) e o /health.

F1: transporte.
F2: conexão com o Config DB no startup (fail-fast) e /health com check_postgres().
F5: list_tools()/call_tool() reais — handlers registrados em mcp_transport/__init__.py,
    que delega para mcp_transport/tools.py (ver F5_MCP_TOOLS_INTEGRATION.md).
"""

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from database.connection import check_postgres, connect_config_db, disconnect_config_db
from mcp_transport import configure_mcp
from mcp_transport import lifespan as mcp_lifespan

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await connect_config_db()  # passo 2 do fluxo de startup (ARQUITETURA.md §6.1) — fail-fast
    try:
        async with mcp_lifespan(app):
            yield
    finally:
        await disconnect_config_db()


app = FastAPI(lifespan=lifespan)
configure_mcp(app)


@app.get("/health")
async def health() -> JSONResponse:
    db_ok = await check_postgres()
    return JSONResponse({"status": "ok" if db_ok else "degraded", "db": db_ok})
