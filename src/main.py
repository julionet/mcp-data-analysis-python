"""Entry point FastAPI — monta o transporte MCP (Streamable HTTP) e o /health.

F1: transporte.
F2: conexão com o Config DB no startup (fail-fast) e /health com check_postgres().
F5: list_tools()/call_tool() reais — handlers registrados em mcp_transport/__init__.py,
    que delega para mcp_transport/tools.py (ver F5_MCP_TOOLS_INTEGRATION.md).
F12: rotas /auth/* (routes/auth.py) e AuthMiddleware no /mcp (mcp_transport/__init__.py).
F7 (ajuste retroativo, 2026-09-27): logging.basicConfig() — sem isso, os
    logger.info() de services/* (ex.: hit/miss de cache) são descartados
    silenciosamente, porque o logger raiz fica no nível WARNING por padrão
    e o uvicorn só configura os loggers "uvicorn.*", não o resto da app.
    Setup mínimo aqui; um formato/handler mais completo fica para o F8
    (Log de Execução).
"""

import contextlib
import logging
from collections.abc import AsyncIterator

# Precisa rodar ANTES de importar mcp_transport/* — mcp_transport/tools.py já
# loga no nível de módulo (qual cache backend está ativo), e isso só chega ao
# console se basicConfig() já tiver rodado quando esse import acontecer.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from database.connection import check_postgres, connect_config_db, disconnect_config_db
from mcp_transport import configure_mcp
from mcp_transport import lifespan as mcp_lifespan
from mcp_transport.tools import analysis_service
from routes.admin_profiles import router as admin_profiles_router
from routes.admin_users import router as admin_users_router
from routes.auth import router as auth_router
from routes.me import router as me_router

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await connect_config_db()  # passo 2 do fluxo de startup (ARQUITETURA.md §6.1) — fail-fast
    try:
        async with mcp_lifespan(app):
            yield
    finally:
        await analysis_service.aclose()  # fecha pools de data source cacheados (F4, ajuste 2026-09-26)
        await disconnect_config_db()


app = FastAPI(lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """F14: 500 JSON genérico para qualquer exceção que escape (hoje /auth/* e /health; os
    handlers do /mcp já são protegidos em tools.py e pelo SDK). Sem stack trace nem str(exc) no
    corpo — o detalhe fica no log do servidor (o Starlette ainda propaga a exceção ao uvicorn)."""
    return JSONResponse(
        {"error": "internal_error", "message": "Erro interno do servidor."}, status_code=500
    )


configure_mcp(app)
app.include_router(auth_router)  # POST /auth/token, POST /auth/revoke — fora do /mcp, sem Bearer
app.include_router(admin_users_router)  # F23: /admin/users — exige administrador
app.include_router(admin_profiles_router)  # F23: /admin/profiles
app.include_router(me_router)  # F23: GET /me, PUT /me/password — qualquer usuário autenticado


@app.get("/health")
async def health() -> JSONResponse:
    db_ok = await check_postgres()
    return JSONResponse({"status": "ok" if db_ok else "degraded", "db": db_ok})
