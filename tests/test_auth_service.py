"""services/auth_service.py — F12_AUTENTICACAO_PERFIS.md §6.1."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import bcrypt
import pytest

from config import settings
from repositories.access_token_repo import AccessToken
from repositories.user_repo import User
from schemas.auth import (
    AuthFailureReason,
    ExpireDaysTooLargeError,
    InvalidCredentialsError,
    InvalidTokenError,
    LoginFailureReason,
    TokenNotFoundError,
)
from security.token_auth import hash_token
from services.auth_service import AuthService

PASSWORD = "s3nha"
PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


def _user(**overrides) -> User:
    data = dict(
        id=uuid4(), name="Maria", external_id="maria@empresa.com",
        password_hash=PASSWORD_HASH, is_blocked=False,
    )
    return User(**{**data, **overrides})


def _token(user: User, **overrides) -> AccessToken:
    data = dict(
        id=uuid4(), user_id=user.id, token_hash="h", label=None,
        expires_at=NOW() + timedelta(days=1), revoked_at=None,
    )
    return AccessToken(**{**data, **overrides})


def _service(user: User | None = None, token: AccessToken | None = None, allowed=frozenset()):
    token_repo, user_repo, profile_repo = AsyncMock(), AsyncMock(), AsyncMock()
    user_repo.get_by_id.return_value = user
    user_repo.get_by_external_id.return_value = user
    token_repo.get_by_hash.return_value = token
    token_repo.create.side_effect = lambda user_id, token_hash, expires_at, label: AccessToken(
        id=uuid4(), user_id=user_id, token_hash=token_hash, label=label,
        expires_at=expires_at, revoked_at=None,
    )
    profile_repo.get_allowed_analysis_ids.return_value = set(allowed)
    return AuthService(token_repo, user_repo, profile_repo), token_repo, user_repo, profile_repo


class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_authenticate_success(self):
        user = _user()
        token = _token(user)
        service, token_repo, _, _ = _service(user, token)

        result = await service.authenticate("raw")

        assert (result.id, result.name) == (user.id, "Maria")
        token_repo.get_by_hash.assert_awaited_once_with(hash_token("raw"))
        token_repo.touch_last_used.assert_awaited_once_with(token.id)

    @pytest.mark.asyncio
    async def test_authenticate_token_not_found(self):
        service, _, user_repo, _ = _service(None, None)

        with pytest.raises(InvalidTokenError) as exc:
            await service.authenticate("raw")

        assert exc.value.reason is AuthFailureReason.TOKEN_NOT_FOUND
        user_repo.get_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_authenticate_token_expired(self):
        user = _user()
        token = _token(user, expires_at=NOW() - timedelta(seconds=1))
        service, _, user_repo, _ = _service(user, token)

        with pytest.raises(InvalidTokenError) as exc:
            await service.authenticate("raw")

        assert exc.value.reason is AuthFailureReason.TOKEN_EXPIRED
        assert (exc.value.token_id, exc.value.user_id) == (token.id, user.id)
        user_repo.get_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_authenticate_token_revoked(self):
        user = _user()
        token = _token(user, revoked_at=NOW())
        service, _, _, _ = _service(user, token)

        with pytest.raises(InvalidTokenError) as exc:
            await service.authenticate("raw")

        assert exc.value.reason is AuthFailureReason.TOKEN_REVOKED

    @pytest.mark.asyncio
    async def test_authenticate_user_blocked(self):
        user = _user(is_blocked=True)
        service, token_repo, _, _ = _service(user, _token(user))

        with pytest.raises(InvalidTokenError) as exc:
            await service.authenticate("raw")

        assert exc.value.reason is AuthFailureReason.USER_BLOCKED
        token_repo.touch_last_used.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_authenticate_user_not_found(self):
        user = _user()
        service, _, user_repo, _ = _service(None, _token(user))

        with pytest.raises(InvalidTokenError) as exc:
            await service.authenticate("raw")

        assert exc.value.reason is AuthFailureReason.USER_NOT_FOUND

    @pytest.mark.asyncio
    async def test_authenticate_error_message_is_always_generic(self):
        service, _, _, _ = _service(None, None)

        with pytest.raises(InvalidTokenError, match="Token de acesso inválido ou ausente."):
            await service.authenticate("raw")

    @pytest.mark.asyncio
    async def test_authenticate_touch_failure_does_not_block(self, caplog):
        user = _user()
        token = _token(user)
        service, token_repo, _, _ = _service(user, token)
        token_repo.touch_last_used.side_effect = RuntimeError("db down")

        with caplog.at_level("WARNING"):
            result = await service.authenticate("raw")

        assert result.id == user.id
        assert "touch_last_used_failed" in caplog.text


class TestIsAnalysisAllowed:
    @pytest.mark.asyncio
    async def test_is_analysis_allowed_true(self):
        analysis_id = uuid4()
        service, _, _, profile_repo = _service(allowed={analysis_id})
        user_id = uuid4()

        assert await service.is_analysis_allowed(user_id, analysis_id) is True
        profile_repo.get_allowed_analysis_ids.assert_awaited_once_with(user_id)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", ["no_profile", "profile_inactive", "analysis_inactive"])
    async def test_is_analysis_allowed_false(self, case):
        # A regra (perfil/análise ativos) vive na query de ProfileRepository; sem linha → fora do conjunto.
        service, _, _, _ = _service(allowed=set())

        assert await service.is_analysis_allowed(uuid4(), uuid4()) is False

    @pytest.mark.asyncio
    async def test_is_analysis_allowed_reads_db_on_every_call(self):
        analysis_id = uuid4()
        service, _, _, profile_repo = _service(allowed={analysis_id})
        user_id = uuid4()

        assert await service.is_analysis_allowed(user_id, analysis_id) is True
        profile_repo.get_allowed_analysis_ids.return_value = set()  # vínculo removido
        assert await service.is_analysis_allowed(user_id, analysis_id) is False
        assert profile_repo.get_allowed_analysis_ids.await_count == 2


class TestIssueToken:
    @pytest.mark.asyncio
    async def test_issue_token_success_default_expiration(self):
        user = _user()
        service, token_repo, _, _ = _service(user)

        raw, expires_at, user_id, token_id = await service.issue_token("maria@empresa.com", PASSWORD, None, None)

        expected = NOW() + timedelta(days=settings.access_token_expiration_days)
        assert abs((expires_at - expected).total_seconds()) < 5
        assert user_id == user.id and token_id is not None
        token_repo.create.assert_awaited_once()
        assert token_repo.create.await_args.args[1] == hash_token(raw)

    @pytest.mark.asyncio
    async def test_issue_token_custom_expire_days_and_label(self):
        service, token_repo, _, _ = _service(_user())

        _, expires_at, _, _ = await service.issue_token("maria@empresa.com", PASSWORD, "Claude Desktop", 30)

        assert abs((expires_at - (NOW() + timedelta(days=30))).total_seconds()) < 5
        assert token_repo.create.await_args.args[3] == "Claude Desktop"

    @pytest.mark.asyncio
    async def test_issue_token_normalizes_email(self):
        service, _, user_repo, _ = _service(_user())

        await service.issue_token("  Maria@Empresa.COM ", PASSWORD, None, None)

        user_repo.get_by_external_id.assert_awaited_once_with("maria@empresa.com")

    @pytest.mark.asyncio
    async def test_issue_token_expire_days_above_max_raises(self):
        service, token_repo, _, _ = _service(_user())

        with pytest.raises(ExpireDaysTooLargeError):
            await service.issue_token(
                "maria@empresa.com", PASSWORD, None, settings.access_token_max_expiration_days + 1
            )

        token_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_issue_token_expire_days_at_max_is_ok(self):
        service, _, _, _ = _service(_user())

        await service.issue_token("maria@empresa.com", PASSWORD, None, settings.access_token_max_expiration_days)

    @pytest.mark.asyncio
    async def test_issue_token_credentials_checked_before_expire_days(self):
        service, _, _, _ = _service(_user())

        with pytest.raises(InvalidCredentialsError):
            await service.issue_token("maria@empresa.com", "errada", None, 99999)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("user", "password", "reason"),
        [
            (None, PASSWORD, LoginFailureReason.USER_NOT_FOUND),
            (_user(password_hash=None), PASSWORD, LoginFailureReason.NO_PASSWORD),
            (_user(), "errada", LoginFailureReason.WRONG_PASSWORD),
            (_user(is_blocked=True), PASSWORD, LoginFailureReason.USER_BLOCKED),
        ],
    )
    async def test_issue_token_invalid_credentials_per_reason(self, user, password, reason):
        service, token_repo, _, _ = _service(user)

        with pytest.raises(InvalidCredentialsError, match="E-mail ou senha inválidos.") as exc:
            await service.issue_token("maria@empresa.com", password, None, None)

        assert exc.value.reason is reason
        assert exc.value.user_id == (user.id if user else None)
        token_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_issue_token_never_persists_raw_token(self):
        service, token_repo, _, _ = _service(_user())

        raw, _, _, _ = await service.issue_token("maria@empresa.com", PASSWORD, "lbl", None)

        persisted = [str(a) for a in token_repo.create.await_args.args]
        assert raw not in persisted
        assert hash_token(raw) in persisted


class TestRevokeToken:
    @pytest.mark.asyncio
    async def test_revoke_token_success(self):
        user = _user()
        token = _token(user)
        service, token_repo, _, _ = _service(user, token)

        result = await service.revoke_token("maria@empresa.com", PASSWORD, "raw")

        assert result == (user.id, token.id)
        token_repo.revoke.assert_awaited_once_with(token.id)

    @pytest.mark.asyncio
    async def test_revoke_token_validates_credentials_before_token_lookup(self):
        user = _user()
        service, token_repo, _, _ = _service(user, _token(user))

        with pytest.raises(InvalidCredentialsError):
            await service.revoke_token("maria@empresa.com", "errada", "raw")

        token_repo.get_by_hash.assert_not_awaited()
        token_repo.revoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_revoke_token_unknown_raises_not_found(self):
        service, token_repo, _, _ = _service(_user(), None)

        with pytest.raises(TokenNotFoundError):
            await service.revoke_token("maria@empresa.com", PASSWORD, "raw")

        token_repo.revoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_revoke_token_of_other_user_raises_not_found(self):
        user = _user()
        foreign = _token(_user())  # outro user_id
        service, token_repo, _, _ = _service(user, foreign)

        with pytest.raises(TokenNotFoundError):
            await service.revoke_token("maria@empresa.com", PASSWORD, "raw")

        token_repo.revoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_revoke_token_already_revoked_or_expired_is_ok(self):
        user = _user()
        for token in (
            _token(user, revoked_at=NOW() - timedelta(days=1)),
            _token(user, expires_at=NOW() - timedelta(days=1)),
        ):
            service, token_repo, _, _ = _service(user, token)

            await service.revoke_token("maria@empresa.com", PASSWORD, "raw")

            token_repo.revoke.assert_awaited_once_with(token.id)
