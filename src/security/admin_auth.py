"""Autenticação e autorização das rotas /admin e /me — F23 §4.2.

Essas rotas ficam fora do AuthMiddleware (que envolve só o /mcp), então a verificação
é uma dependência FastAPI. `require_admin` lê `is_admin`/`is_blocked` do BD a cada
chamada: remover o papel ou bloquear corta o acesso na chamada seguinte.
"""

import logging

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from repositories.user_repo import UserRepository
from routes.auth import get_auth_service
from routes.dependencies import get_user_repo
from schemas.admin import ForbiddenError, UnauthorizedError
from schemas.auth import TOKEN_ERROR_MESSAGE, AuthenticatedUser, InvalidTokenError
from security.auth_middleware import _extract_bearer
from services.auth_service import AuthService

logger = logging.getLogger(__name__)

FORBIDDEN_MESSAGE = "Acesso restrito a administradores."

# F16: declara o esquema Bearer no OpenAPI (botão "Authorize" do Swagger). `auto_error=False` é
# essencial: sem token esta dependência NÃO levanta o 403 do FastAPI — quem responde é
# `get_current_user`, com o 401 {"error": "unauthorized"} de sempre.
bearer_scheme = HTTPBearer(
    scheme_name="BearerToken",
    description=(
        "Token opaco emitido por `POST /auth/token`. Cole apenas o token "
        "(o Swagger acrescenta o prefixo `Bearer`)."
    ),
    auto_error=False,
)


async def get_current_user(
    request: Request,
    _credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),  # só registra o esquema
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthenticatedUser:
    try:
        return await auth_service.authenticate(_extract_bearer(request.scope))
    except InvalidTokenError as exc:
        logger.warning(
            "auth_failed reason=%s client_ip=%s method=%s path=%s token_id=%s user_id=%s",
            exc.reason.value,
            request.client.host if request.client else None,
            request.method,
            request.url.path,
            exc.token_id,
            exc.user_id,
        )
        raise UnauthorizedError(TOKEN_ERROR_MESSAGE, headers={"WWW-Authenticate": "Bearer"}) from exc


async def require_admin(
    user: AuthenticatedUser = Depends(get_current_user),
    users: UserRepository = Depends(get_user_repo),
) -> AuthenticatedUser:
    record = await users.get_by_id(user.id)
    if record is None or record.is_blocked or not record.is_admin:
        logger.warning("admin_denied user_id=%s path_checked=admin", user.id)
        raise ForbiddenError(FORBIDDEN_MESSAGE)
    return user
