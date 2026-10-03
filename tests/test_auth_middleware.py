"""security/auth_middleware.py — F12_AUTENTICACAO_PERFIS.md §6.1.

Usa um app ASGI de brinquedo: sem lifespan, sem banco, sem o limite do session_manager.
"""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from schemas.auth import AuthFailureReason, InvalidTokenError
from security.auth_middleware import AuthMiddleware, current_user
from tests.helpers import make_user

RAW_TOKEN = "super-secret-raw-token"
_USERS = {"token-a": make_user("A"), "token-b": make_user("B")}


async def _authenticate(raw_token: str):
    if raw_token not in _USERS:
        raise InvalidTokenError(AuthFailureReason.TOKEN_NOT_FOUND)
    return _USERS[raw_token]


async def _toy_app(scope, receive, send):
    """Devolve o nome do usuário visto no contextvar (depois de ceder o loop)."""
    await asyncio.sleep(0.05)
    user = current_user.get()
    body = json.dumps({"user": user.name if user else None}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": body})


def _client(app=None, authenticate=_authenticate) -> httpx.AsyncClient:
    middleware = AuthMiddleware(app or _toy_app, authenticate)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=middleware), base_url="http://test")


def _failing(reason: AuthFailureReason, token_id=None, user_id=None):
    async def authenticate(_raw: str):
        raise InvalidTokenError(reason, token_id, user_id)

    return authenticate


_GENERIC_BODY = {"error": "unauthorized", "message": "Token de acesso inválido ou ausente."}


class TestAuthMiddleware:
    @pytest.mark.asyncio
    async def test_missing_header_returns_401(self):
        async with _client() as c:
            response = await c.post("/mcp")

        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json() == _GENERIC_BODY

    @pytest.mark.asyncio
    @pytest.mark.parametrize("header", ["Basic xxx", "Bearer", "Bearer   ", "token-a", ""])
    async def test_malformed_header_returns_401(self, header):
        async with _client() as c:
            response = await c.post("/mcp", headers={"Authorization": header})

        assert response.status_code == 401
        assert response.json() == _GENERIC_BODY

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self):
        async with _client() as c:
            response = await c.post("/mcp", headers={"Authorization": "Bearer nope"})

        assert response.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
    async def test_bearer_scheme_is_case_insensitive(self, scheme):
        async with _client() as c:
            response = await c.post("/mcp", headers={"Authorization": f"{scheme} token-a"})

        assert response.status_code == 200
        assert response.json() == {"user": "A"}

    @pytest.mark.asyncio
    async def test_all_rejections_have_identical_response(self):
        cases = [
            ({}, _authenticate),  # sem header
            ({"Authorization": "Basic xxx"}, _authenticate),  # malformado
            ({"Authorization": "Bearer x"}, _failing(AuthFailureReason.TOKEN_NOT_FOUND)),
            ({"Authorization": "Bearer x"}, _failing(AuthFailureReason.TOKEN_EXPIRED, uuid4(), uuid4())),
            ({"Authorization": "Bearer x"}, _failing(AuthFailureReason.TOKEN_REVOKED, uuid4(), uuid4())),
            ({"Authorization": "Bearer x"}, _failing(AuthFailureReason.USER_BLOCKED, uuid4(), uuid4())),
            ({"Authorization": "Bearer x"}, _failing(AuthFailureReason.USER_NOT_FOUND, uuid4(), uuid4())),
        ]
        seen = set()
        for headers, authenticate in cases:
            async with _client(authenticate=authenticate) as c:
                r = await c.post("/mcp", headers=headers)
            seen.add((r.status_code, r.headers["www-authenticate"], r.headers["content-type"], r.text))

        assert len(seen) == 1
        assert next(iter(seen))[0] == 401

    @pytest.mark.asyncio
    async def test_valid_token_sets_contextvar_per_request(self):
        """2 requisições simultâneas, usuários distintos, sem mistura."""
        async with _client() as c:
            results = await asyncio.gather(
                *[
                    c.post("/mcp", headers={"Authorization": f"Bearer token-{'a' if i % 2 == 0 else 'b'}"})
                    for i in range(10)
                ]
            )

        assert [r.json()["user"] for r in results] == ["A", "B"] * 5

    @pytest.mark.asyncio
    async def test_contextvar_reset_after_request(self):
        async with _client() as c:
            await c.post("/mcp", headers={"Authorization": "Bearer token-a"})

        assert current_user.get() is None

    @pytest.mark.asyncio
    async def test_contextvar_reset_even_when_handler_raises(self):
        async def boom(scope, receive, send):
            raise RuntimeError("handler quebrou")

        middleware = AuthMiddleware(boom, _authenticate)
        scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": [(b"authorization", b"Bearer token-a")]}

        with pytest.raises(RuntimeError):
            await middleware(scope, None, None)

        assert current_user.get() is None

    @pytest.mark.asyncio
    async def test_handler_is_not_reached_on_rejection(self):
        called = False

        async def app(scope, receive, send):
            nonlocal called
            called = True

        async with _client(app=app) as c:
            await c.post("/mcp")

        assert called is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("reason", list(AuthFailureReason))
    async def test_auth_failure_logs_reason_per_case(self, reason, caplog):
        token_id, user_id = uuid4(), uuid4()
        if reason is AuthFailureReason.MISSING_HEADER:
            authenticate, headers = _authenticate, {}
        elif reason is AuthFailureReason.MALFORMED_HEADER:
            authenticate, headers = _authenticate, {"Authorization": "Basic xxx"}
        else:
            authenticate, headers = _failing(reason, token_id, user_id), {"Authorization": f"Bearer {RAW_TOKEN}"}

        with caplog.at_level("WARNING", logger="security.auth_middleware"):
            async with _client(authenticate=authenticate) as c:
                await c.post("/mcp", headers=headers)

        records = [r for r in caplog.records if r.name == "security.auth_middleware"]
        assert len(records) == 1 and records[0].levelname == "WARNING"
        message = records[0].getMessage()
        assert message.startswith("auth_failed ")
        assert f"reason={reason.value}" in message
        assert "client_ip=" in message and "method=POST" in message and "path=/mcp" in message
        if reason not in (AuthFailureReason.MISSING_HEADER, AuthFailureReason.MALFORMED_HEADER, AuthFailureReason.TOKEN_NOT_FOUND):
            assert f"token_id={token_id}" in message and f"user_id={user_id}" in message

    @pytest.mark.asyncio
    async def test_auth_failure_log_never_contains_token_or_hash(self, caplog):
        from security.token_auth import hash_token

        with caplog.at_level("DEBUG"):
            for headers in (
                {"Authorization": f"Bearer {RAW_TOKEN}"},
                {"Authorization": f"Basic {RAW_TOKEN}"},
            ):
                async with _client() as c:
                    await c.post("/mcp", headers=headers)

        assert RAW_TOKEN not in caplog.text
        assert hash_token(RAW_TOKEN) not in caplog.text
        assert "Authorization" not in caplog.text and "Bearer" not in caplog.text
