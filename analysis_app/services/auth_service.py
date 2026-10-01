"""Autenticação por token opaco e autorização por perfis — F12_AUTENTICACAO_PERFIS.md §4.2/§4.4.

O motivo de cada recusa vai nos atributos das exceções (`reason`, `user_id`...)
e só é logado pelos chamadores (§4.5); o cliente nunca o vê.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from config import settings
from repositories.access_token_repo import AccessTokenRepository
from repositories.profile_repo import ProfileRepository
from repositories.user_repo import User, UserRepository
from schemas.auth import (
    AuthenticatedUser,
    AuthFailureReason,
    ExpireDaysTooLargeError,
    InvalidCredentialsError,
    InvalidTokenError,
    LoginFailureReason,
    TokenNotFoundError,
)
from security.password_hash import verify_password
from security.token_auth import generate_token, hash_token

logger = logging.getLogger(__name__)

# Hash bcrypt (custo 12) de uma senha qualquer. Conferido contra a senha recebida
# quando o e-mail não existe / não tem senha, para o tempo de resposta não revelar
# se o e-mail está cadastrado (§4.4, verify_password).
_DUMMY_PASSWORD_HASH = "$2b$12$J/VwFrHptiT8q.v1PbA.C.JzBZYOGZOxLNsF/.FOjDkclizShE20S"


class AuthService:
    def __init__(
        self,
        token_repo: AccessTokenRepository,
        user_repo: UserRepository,
        profile_repo: ProfileRepository,
    ) -> None:
        self.token_repo = token_repo
        self.user_repo = user_repo
        self.profile_repo = profile_repo

    async def authenticate(self, raw_token: str) -> AuthenticatedUser:
        """Levanta InvalidTokenError se o token for inexistente/expirado/revogado
        ou o usuário inexistente/bloqueado — sem tocar em nenhuma tabela de negócio.
        Nunca lança para "análise não permitida" (isso é is_analysis_allowed())."""
        token = await self.token_repo.get_by_hash(hash_token(raw_token))
        if token is None:
            raise InvalidTokenError(AuthFailureReason.TOKEN_NOT_FOUND)
        if token.revoked_at is not None:
            raise InvalidTokenError(AuthFailureReason.TOKEN_REVOKED, token.id, token.user_id)
        if token.expires_at < datetime.now(timezone.utc):
            raise InvalidTokenError(AuthFailureReason.TOKEN_EXPIRED, token.id, token.user_id)

        user = await self.user_repo.get_by_id(token.user_id)
        if user is None:
            raise InvalidTokenError(AuthFailureReason.USER_NOT_FOUND, token.id, token.user_id)
        if user.is_blocked:
            raise InvalidTokenError(AuthFailureReason.USER_BLOCKED, token.id, user.id)

        try:
            await self.token_repo.touch_last_used(token.id)
        except Exception as exc:  # observabilidade apenas — não bloqueia a chamada
            logger.warning("touch_last_used_failed token_id=%s error=%s", token.id, exc)

        return AuthenticatedUser(id=user.id, name=user.name)

    async def _validate_credentials(self, email: str, password: str) -> User:
        email = email.strip().lower()
        user = await self.user_repo.get_by_external_id(email)
        password_hash = user.password_hash if user is not None else None
        # Sempre roda um bcrypt (hash real ou fictício), em thread: bcrypt é CPU-bound
        # e o tempo não pode revelar se o e-mail existe.
        password_ok = await asyncio.to_thread(
            verify_password, password, password_hash or _DUMMY_PASSWORD_HASH
        )

        if user is None:
            raise InvalidCredentialsError(LoginFailureReason.USER_NOT_FOUND)
        if not user.password_hash:
            raise InvalidCredentialsError(LoginFailureReason.NO_PASSWORD, user.id)
        if user.is_blocked:
            raise InvalidCredentialsError(LoginFailureReason.USER_BLOCKED, user.id)
        if not password_ok:
            raise InvalidCredentialsError(LoginFailureReason.WRONG_PASSWORD, user.id)
        return user

    async def issue_token(
        self, email: str, password: str, label: str | None, expire_days: int | None
    ) -> tuple[str, datetime, UUID, UUID]:
        """Valida e-mail/senha (InvalidCredentialsError) e emite um token. Devolve
        `(token_bruto, expires_at, user_id, token_id)` — o bruto sai só aqui, 1 vez;
        user_id/token_id existem para o log INFO da rota (§4.5)."""
        user = await self._validate_credentials(email, password)

        if expire_days is None:
            expire_days = settings.access_token_expiration_days
        elif expire_days > settings.access_token_max_expiration_days:
            raise ExpireDaysTooLargeError(settings.access_token_max_expiration_days)

        raw_token = generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(days=expire_days)
        created = await self.token_repo.create(user.id, hash_token(raw_token), expires_at, label)
        return raw_token, expires_at, user.id, created.id

    async def revoke_token(self, email: str, password: str, raw_token: str) -> tuple[UUID, UUID]:
        """Valida e-mail/senha PRIMEIRO; depois localiza o token (TokenNotFoundError se
        inexistente ou de outro usuário) e o revoga. Token já revogado/expirado é aceito.
        Devolve `(user_id, token_id)` para o log INFO da rota."""
        user = await self._validate_credentials(email, password)
        token = await self.token_repo.get_by_hash(hash_token(raw_token))
        if token is None or token.user_id != user.id:
            raise TokenNotFoundError(user.id)
        await self.token_repo.revoke(token.id)
        return user.id, token.id

    async def is_analysis_allowed(self, user_id: UUID, analysis_id: UUID) -> bool:
        """Reconsulta o BD a cada chamada, sem cache — mudança de perfil vale na hora."""
        return analysis_id in await self.profile_repo.get_allowed_analysis_ids(user_id)
