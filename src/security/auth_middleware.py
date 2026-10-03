"""Middleware ASGI de autenticação do /mcp — F12_AUTENTICACAO_PERFIS.md §4.2/§4.5.

Lê `Authorization: Bearer <token>`, valida via `authenticate` e guarda o
`AuthenticatedUser` num contextvar lido pelos handlers de list_tools()/call_tool().
Qualquer recusa responde o mesmo 401 genérico (o motivo real só vai para o log).

Funciona porque o transporte é stateless (stateless=True em mcp_transport): a task
do servidor MCP nasce dentro de cada requisição e herda o contextvar.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from schemas.auth import (
    TOKEN_ERROR_MESSAGE,
    AuthenticatedUser,
    AuthFailureReason,
    InvalidTokenError,
)

logger = logging.getLogger(__name__)

current_user: ContextVar[AuthenticatedUser | None] = ContextVar("current_user", default=None)

Authenticator = Callable[[str], Awaitable[AuthenticatedUser]]

_UNAUTHORIZED_BODY = json.dumps(
    {"error": "unauthorized", "message": TOKEN_ERROR_MESSAGE}, ensure_ascii=False
).encode("utf-8")


def _extract_bearer(scope) -> str:
    """Devolve o token bruto ou levanta InvalidTokenError (header ausente/malformado).
    O esquema `Bearer` não diferencia maiúsculas/minúsculas (RFC 7235)."""
    header = None
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            header = value.decode("latin-1")
            break
    if header is None:
        raise InvalidTokenError(AuthFailureReason.MISSING_HEADER)
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise InvalidTokenError(AuthFailureReason.MALFORMED_HEADER)
    return token


class AuthMiddleware:
    """Envolve diretamente os endpoints do /mcp (rota exata e mount /mcp/...) —
    não há filtro de path aqui: tudo o que chega a este middleware é /mcp, então
    um path alterado pelo Mount do Starlette nunca vira bypass de autenticação.
    /health e /auth/* nunca passam por ele. O CORSMiddleware fica por fora: o
    preflight OPTIONS (sem Authorization) é respondido antes daqui, e o 401 sai
    com os headers CORS."""

    def __init__(self, app, authenticate: Authenticator) -> None:
        self.app = app
        self._authenticate = authenticate

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            user = await self._authenticate(_extract_bearer(scope))
        except InvalidTokenError as exc:
            client = scope.get("client")
            logger.warning(
                "auth_failed reason=%s client_ip=%s method=%s path=%s token_id=%s user_id=%s",
                exc.reason.value,
                client[0] if client else None,
                scope["method"],
                scope["path"],
                exc.token_id,
                exc.user_id,
            )
            await self._send_unauthorized(send)
            return

        reset_token = current_user.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user.reset(reset_token)

    @staticmethod
    async def _send_unauthorized(send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"www-authenticate", b"Bearer"),
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_UNAUTHORIZED_BODY)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY})
