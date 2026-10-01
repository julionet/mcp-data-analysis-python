"""POST /auth/token e POST /auth/revoke — F12_AUTENTICACAO_PERFIS.md §4.2/§4.5.

Fora do /mcp: não exigem `Authorization` (o usuário prova quem é com e-mail + senha).
Os logs nunca trazem senha, hash nem o e-mail informado — só `user_id` (quando o
e-mail existe) e o IP.
"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from schemas.auth import (
    CREDENTIALS_ERROR_MESSAGE,
    ExpireDaysTooLargeError,
    InvalidCredentialsError,
    RevokeRequest,
    TokenNotFoundError,
    TokenRequest,
    TokenResponse,
)
from services.auth_service import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service() -> AuthService:
    """Dependência FastAPI: devolve a instância única criada em mcp_transport/tools.py.
    Import tardio — evita puxar o Config DB/serviços ao importar este módulo, e os
    testes de rota a trocam por app.dependency_overrides."""
    from mcp_transport.tools import auth_service

    return auth_service


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _invalid_credentials(endpoint: str, request: Request, exc: InvalidCredentialsError) -> JSONResponse:
    logger.warning(
        "login_failed endpoint=%s reason=%s client_ip=%s user_id=%s",
        endpoint,
        exc.reason.value,
        _client_ip(request),
        exc.user_id,
    )
    return JSONResponse(
        status_code=401,
        content={"error": "invalid_credentials", "message": CREDENTIALS_ERROR_MESSAGE},
    )


@router.post("/token", response_model=TokenResponse)
async def issue_token(
    body: TokenRequest, request: Request, auth_service: AuthService = Depends(get_auth_service)
):
    try:
        token, expires_at, user_id, token_id = await auth_service.issue_token(
            body.email, body.password, body.label, body.expire_days
        )
    except InvalidCredentialsError as exc:
        return _invalid_credentials("/auth/token", request, exc)
    except ExpireDaysTooLargeError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_expire_days", "message": str(exc)},
        )

    logger.info(
        'token_issued user_id=%s token_id=%s label="%s" expires_at=%s',
        user_id,
        token_id,
        body.label or "",
        expires_at.isoformat(),
    )
    return TokenResponse(token=token, expires_at=expires_at)


@router.post("/revoke")
async def revoke_token(
    body: RevokeRequest, request: Request, auth_service: AuthService = Depends(get_auth_service)
):
    try:
        user_id, token_id = await auth_service.revoke_token(body.email, body.password, body.token)
    except InvalidCredentialsError as exc:
        return _invalid_credentials("/auth/revoke", request, exc)
    except TokenNotFoundError as exc:
        logger.warning(
            "revoke_token_not_found endpoint=/auth/revoke client_ip=%s user_id=%s",
            _client_ip(request),
            exc.user_id,
        )
        return JSONResponse(
            status_code=404,
            content={"error": "token_not_found", "message": "Token não encontrado."},
        )

    logger.info("token_revoked user_id=%s token_id=%s", user_id, token_id)
    return {"status": "revoked"}
