"""Rota que traduz `AdminError` para `{"error", "message"}` — F23 §4.5 / ADR-008.

Usada como `route_class` dos routers de /admin e /me: funciona também em apps de teste
montados só com `include_router`, sem handlers globais. A exceção levantada pelas
dependências (401/403) também passa por aqui, pois elas rodam dentro do handler.
"""

from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from schemas.admin import AdminError, InvalidPasswordError
from security.password_hash import PasswordPolicyError


class AdminRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except PasswordPolicyError as policy_exc:
                error: AdminError = InvalidPasswordError(policy_exc.reason)
            except AdminError as admin_exc:
                error = admin_exc
            return JSONResponse(
                status_code=error.status_code,
                content={"error": error.error, "message": error.message},
                headers=error.headers,
            )

        return handler
