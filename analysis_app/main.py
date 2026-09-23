"""Entry point FastAPI — monta o transporte MCP (Streamable HTTP) e o /health.

F1: apenas transporte. list_tools()/call_tool() reais entram em F5.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from mcp_transport import configure_mcp, lifespan

app = FastAPI(lifespan=lifespan)
configure_mcp(app)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})  # confirmado: apenas isso nesta feature
