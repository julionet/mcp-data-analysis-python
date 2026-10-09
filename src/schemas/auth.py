"""Tipos do F12 — autenticação e controle de acesso (F12_AUTENTICACAO_PERFIS.md §4.4).

Identificadores são `uuid.UUID` em todo o código Python; só viram `str` nas
bordas (log, JSON).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

TOKEN_ERROR_MESSAGE = "Token de acesso inválido ou ausente."
CREDENTIALS_ERROR_MESSAGE = "E-mail ou senha inválidos."


@dataclass
class AuthenticatedUser:
    id: UUID
    name: str


class AuthFailureReason(str, Enum):
    MISSING_HEADER = "missing_header"
    MALFORMED_HEADER = "malformed_header"
    TOKEN_NOT_FOUND = "token_not_found"
    TOKEN_EXPIRED = "token_expired"
    TOKEN_REVOKED = "token_revoked"
    USER_BLOCKED = "user_blocked"
    USER_NOT_FOUND = "user_not_found"


class InvalidTokenError(Exception):
    """Token ausente, inválido, expirado, revogado, ou usuário bloqueado/inexistente.

    A mensagem é sempre a mesma genérica — o motivo real nunca é exposto ao
    cliente (§4.2); vai em `reason`/`token_id`/`user_id`, só para o log (§4.5).
    """

    def __init__(
        self,
        reason: AuthFailureReason,
        token_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> None:
        super().__init__(TOKEN_ERROR_MESSAGE)
        self.reason = reason
        self.token_id = token_id
        self.user_id = user_id


class LoginFailureReason(str, Enum):
    USER_NOT_FOUND = "user_not_found"
    NO_PASSWORD = "no_password"
    WRONG_PASSWORD = "wrong_password"
    USER_BLOCKED = "user_blocked"


class InvalidCredentialsError(Exception):
    """E-mail/senha inválidos (inexistente, sem senha, senha errada ou bloqueado).
    Mensagem sempre genérica; o motivo real vai em `reason`/`user_id`, só para o log."""

    def __init__(self, reason: LoginFailureReason, user_id: UUID | None = None) -> None:
        super().__init__(CREDENTIALS_ERROR_MESSAGE)
        self.reason = reason
        self.user_id = user_id


class TokenNotFoundError(Exception):
    """Token inexistente ou de outro usuário, em /auth/revoke (após credenciais válidas)."""

    def __init__(self, user_id: UUID | None = None) -> None:
        super().__init__("Token não encontrado.")
        self.user_id = user_id


class ExpireDaysTooLargeError(Exception):
    """expire_days > ACCESS_TOKEN_MAX_EXPIRATION_DAYS (mapeado para 400)."""

    def __init__(self, max_days: int) -> None:
        super().__init__(f"expire_days máximo: {max_days}.")
        self.max_days = max_days


class TokenRequest(BaseModel):
    email: str = Field(max_length=255, description="E-mail (login) do usuário.")  # = tamanho de users.external_id
    password: str = Field(max_length=256, description="Senha do usuário.")  # o bcrypt só aceita 72 bytes de qualquer forma
    label: str | None = Field(
        default=None, max_length=255, description="Rótulo livre para identificar o token (ex.: `claude-code`)."
    )  # = access_tokens.label
    expire_days: int | None = Field(
        default=None, ge=1, description="Validade em dias; omitido usa o padrão do servidor (limitado ao máximo configurado)."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "maria@exemplo.com",
                "password": "Exemplo@123",
                "label": "claude-code",
                "expire_days": 90,
            }
        }
    }


class TokenResponse(BaseModel):
    token: str = Field(description="Token opaco. Exibido apenas nesta resposta; guarde-o.")
    token_type: str = "Bearer"
    expires_at: datetime = Field(description="Data/hora de expiração do token.")


class RevokeRequest(BaseModel):
    email: str = Field(max_length=255, description="E-mail (login) do dono do token.")
    password: str = Field(max_length=256, description="Senha do usuário.")
    token: str = Field(max_length=256, description="Token a revogar.")  # token_urlsafe(32) tem 43 caracteres

    model_config = {
        "json_schema_extra": {
            "example": {"email": "maria@exemplo.com", "password": "Exemplo@123", "token": "<token a revogar>"}
        }
    }
