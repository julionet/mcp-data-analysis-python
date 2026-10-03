"""routes/auth.py — POST /auth/token e POST /auth/revoke (F12_AUTENTICACAO_PERFIS.md §6.1).

Os testes de rota montam um FastAPI mínimo (sem lifespan/banco) com um AuthService
real sobre repositórios em memória. `test_revoked_token_gets_401_on_mcp` usa o app real.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import settings
from mcp_transport import tools
from repositories.access_token_repo import AccessToken
from repositories.user_repo import User
from routes.auth import get_auth_service, router
from security.token_auth import hash_token
from services.auth_service import AuthService

PASSWORD = "s3nha"
PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
EMAIL = "maria@empresa.com"
_INVALID_CREDENTIALS = {"error": "invalid_credentials", "message": "E-mail ou senha inválidos."}


class FakeTokenRepo:
    def __init__(self) -> None:
        self.tokens: dict[str, AccessToken] = {}

    async def get_by_hash(self, token_hash):
        return self.tokens.get(token_hash)

    async def create(self, user_id, token_hash, expires_at, label):
        token = AccessToken(uuid4(), user_id, token_hash, label, expires_at, None)
        self.tokens[token_hash] = token
        return token

    async def touch_last_used(self, token_id):
        pass

    async def revoke(self, token_id):
        for token in self.tokens.values():
            if token.id == token_id and token.revoked_at is None:
                token.revoked_at = datetime.now(timezone.utc)


class FakeUserRepo:
    def __init__(self, *users: User) -> None:
        self.users = list(users)

    async def get_by_id(self, user_id):
        return next((u for u in self.users if u.id == user_id), None)

    async def get_by_external_id(self, external_id):
        return next((u for u in self.users if u.external_id == external_id), None)


def _user(email=EMAIL, **overrides) -> User:
    data = dict(id=uuid4(), name="Maria", external_id=email, password_hash=PASSWORD_HASH, is_blocked=False)
    return User(**{**data, **overrides})


def _service(*users: User) -> tuple[AuthService, FakeTokenRepo]:
    token_repo = FakeTokenRepo()
    return AuthService(token_repo, FakeUserRepo(*users), AsyncMock()), token_repo


def _app(service: AuthService) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_auth_service] = lambda: service
    return TestClient(app)


def _creds(**overrides) -> dict:
    return {"email": EMAIL, "password": PASSWORD, **overrides}


class TestAuthRoutes:
    def test_post_token_200(self):
        service, repo = _service(_user())

        response = _app(service).post("/auth/token", json=_creds(label="Claude Desktop"))

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "Bearer"
        assert hash_token(body["token"]) in repo.tokens
        assert body["token"] not in json.dumps([vars(t) for t in repo.tokens.values()], default=str)
        expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        expected = datetime.now(timezone.utc) + timedelta(days=settings.access_token_expiration_days)
        assert abs((expires - expected).total_seconds()) < 10
        assert repo.tokens[hash_token(body["token"])].label == "Claude Desktop"

    def test_post_token_normalizes_email(self):
        service, _ = _service(_user())

        response = _app(service).post("/auth/token", json=_creds(email="  Maria@Empresa.COM "))

        assert response.status_code == 200

    def test_post_token_expire_days(self):
        service, repo = _service(_user())

        response = _app(service).post("/auth/token", json=_creds(expire_days=30))

        expires = datetime.fromisoformat(response.json()["expires_at"].replace("Z", "+00:00"))
        assert abs((expires - (datetime.now(timezone.utc) + timedelta(days=30))).total_seconds()) < 10

    def test_post_token_401_identical_body_for_all_credential_failures(self):
        cases = [
            (_service(), _creds()),  # e-mail inexistente
            (_service(_user(password_hash=None)), _creds()),  # sem senha
            (_service(_user()), _creds(password="errada")),  # senha errada
            (_service(_user(is_blocked=True)), _creds()),  # bloqueado
        ]
        for (service, repo), body in cases:
            response = _app(service).post("/auth/token", json=body)

            assert response.status_code == 401
            assert response.json() == _INVALID_CREDENTIALS
            assert repo.tokens == {}

    def test_post_token_400_expire_days_above_max(self):
        service, repo = _service(_user())
        max_days = settings.access_token_max_expiration_days

        response = _app(service).post("/auth/token", json=_creds(expire_days=max_days + 1))

        assert response.status_code == 400
        assert response.json() == {
            "error": "invalid_expire_days",
            "message": f"expire_days máximo: {max_days}.",
        }
        assert repo.tokens == {}

    def test_post_token_422_expire_days_below_one(self):
        service, repo = _service(_user())

        response = _app(service).post("/auth/token", json=_creds(expire_days=0))

        assert response.status_code == 422
        assert repo.tokens == {}

    def test_post_token_422_field_too_long(self):
        service, _ = _service(_user())
        client = _app(service)

        assert client.post("/auth/token", json=_creds(label="x" * 256)).status_code == 422
        assert client.post("/auth/token", json=_creds(password="x" * 257)).status_code == 422
        assert client.post("/auth/token", json={"email": EMAIL}).status_code == 422

    def test_post_revoke_200(self):
        service, repo = _service(_user())
        client = _app(service)
        token = client.post("/auth/token", json=_creds()).json()["token"]

        response = client.post("/auth/revoke", json=_creds(token=token))

        assert response.status_code == 200
        assert response.json() == {"status": "revoked"}
        assert repo.tokens[hash_token(token)].revoked_at is not None

    def test_post_revoke_twice_is_ok(self):
        service, _ = _service(_user())
        client = _app(service)
        token = client.post("/auth/token", json=_creds()).json()["token"]

        assert client.post("/auth/revoke", json=_creds(token=token)).status_code == 200
        assert client.post("/auth/revoke", json=_creds(token=token)).status_code == 200

    def test_post_revoke_401_before_token_lookup(self):
        service, repo = _service(_user())
        client = _app(service)
        token = client.post("/auth/token", json=_creds()).json()["token"]

        existing = client.post("/auth/revoke", json=_creds(password="errada", token=token))
        unknown = client.post("/auth/revoke", json=_creds(password="errada", token="nao-existe"))

        assert existing.status_code == unknown.status_code == 401
        assert existing.json() == unknown.json() == _INVALID_CREDENTIALS
        assert repo.tokens[hash_token(token)].revoked_at is None

    def test_post_revoke_404_unknown_or_foreign_token(self):
        maria, joao = _user(), _user("joao@empresa.com", name="João")
        service, repo = _service(maria, joao)
        client = _app(service)
        joao_token = client.post("/auth/token", json=_creds(email="joao@empresa.com")).json()["token"]

        for token in ("nao-existe", joao_token):
            response = client.post("/auth/revoke", json=_creds(token=token))

            assert response.status_code == 404
            assert response.json() == {"error": "token_not_found", "message": "Token não encontrado."}
        assert repo.tokens[hash_token(joao_token)].revoked_at is None

    def test_multiple_tokens_are_independent(self):
        service, repo = _service(_user())
        client = _app(service)
        t1 = client.post("/auth/token", json=_creds(label="Claude Desktop")).json()["token"]
        t2 = client.post("/auth/token", json=_creds(label="Gemini Desktop")).json()["token"]

        client.post("/auth/revoke", json=_creds(token=t1))

        assert repo.tokens[hash_token(t1)].revoked_at is not None
        assert repo.tokens[hash_token(t2)].revoked_at is None

    def test_auth_routes_do_not_require_authorization_header(self):
        service, _ = _service(_user())
        client = _app(service)

        assert "authorization" not in {k.lower() for k in client.headers}
        assert client.post("/auth/token", json=_creds()).status_code == 200

    def test_login_failure_log_has_no_password_hash_or_email(self, caplog):
        user = _user()
        service, _ = _service(user)

        with caplog.at_level("INFO"):
            _app(service).post("/auth/token", json=_creds(password="errada-123"))

        messages = [r.getMessage() for r in caplog.records if r.name == "routes.auth"]
        assert len(messages) == 1
        assert messages[0].startswith("login_failed endpoint=/auth/token reason=wrong_password")
        assert f"user_id={user.id}" in messages[0] and "client_ip=" in messages[0]
        assert "errada-123" not in caplog.text
        assert PASSWORD_HASH not in caplog.text
        assert EMAIL not in caplog.text and "empresa.com" not in caplog.text

    def test_login_failure_unknown_email_logs_without_user_id(self, caplog):
        service, _ = _service()

        with caplog.at_level("INFO"):
            _app(service).post("/auth/token", json=_creds())

        message = next(r.getMessage() for r in caplog.records if r.name == "routes.auth")
        assert "reason=user_not_found" in message and "user_id=None" in message
        assert "empresa.com" not in caplog.text

    def test_token_issue_and_revoke_are_logged_without_secrets(self, caplog):
        service, _ = _service(_user())
        client = _app(service)

        with caplog.at_level("INFO"):
            token = client.post("/auth/token", json=_creds(label="Claude Desktop")).json()["token"]
            client.post("/auth/revoke", json=_creds(token=token))

        text = "\n".join(r.getMessage() for r in caplog.records if r.name == "routes.auth")
        assert "token_issued user_id=" in text and 'label="Claude Desktop"' in text
        assert "token_revoked user_id=" in text
        assert token not in caplog.text and hash_token(token) not in caplog.text
        assert PASSWORD not in caplog.text

    def test_revoke_not_found_is_logged(self, caplog):
        service, _ = _service(_user())

        with caplog.at_level("WARNING"):
            _app(service).post("/auth/revoke", json=_creds(token="nao-existe"))

        assert "revoke_token_not_found" in caplog.text
        assert "nao-existe" not in caplog.text

    def test_revoked_token_gets_401_on_mcp(self, client: TestClient):
        """Fluxo completo sobre o app real: emite → /mcp ok → revoga → /mcp 401."""
        user = _user()
        service, _ = _service(user)
        headers = {"Accept": "application/json, text/event-stream"}
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

        with (
            patch.object(tools.auth_service, "token_repo", service.token_repo),
            patch.object(tools.auth_service, "user_repo", service.user_repo),
            patch.object(tools.analysis_service, "get_allowed_analyses", AsyncMock(return_value=[])),
        ):
            token = client.post("/auth/token", json=_creds()).json()["token"]
            auth = {**headers, "Authorization": f"Bearer {token}"}
            assert client.post("/mcp", json=body, headers=auth).status_code == 200

            assert client.post("/auth/revoke", json=_creds(token=token)).status_code == 200
            response = client.post("/mcp", json=body, headers=auth)

        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"
