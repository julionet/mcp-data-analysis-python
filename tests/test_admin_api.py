"""API administrativa /admin/users, /admin/profiles e /me — F23 §6.1.

FastAPI mínimo (sem lifespan/banco) com os serviços reais sobre repositórios em memória.
"""

import logging
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from routes.admin_profiles import router as profiles_router
from routes.admin_users import router as users_router
from routes.auth import get_auth_service
from routes.dependencies import (
    get_profile_admin_service,
    get_user_admin_service,
    get_user_repo,
)
from routes.me import router as me_router
from security.password_hash import PasswordPolicyError, hash_password, validate_password_policy, verify_password
from services.auth_service import AuthService
from services.profile_admin_service import ProfileAdminService
from services.user_admin_service import UserAdminService
from tests.admin_fakes import (
    FakeDb,
    FakeProfileRepo,
    FakeTokenRepo,
    FakeUserRepo,
    Store,
)

ADMIN_TOKEN = "admin-token"
USER_TOKEN = "user-token"
GOOD_PASSWORD = "Nova#Senha1"


class Env:
    def __init__(self) -> None:
        self.store = Store()
        self.db = FakeDb(self.store)
        users, tokens, profiles = FakeUserRepo(self.store), FakeTokenRepo(self.store), FakeProfileRepo(self.store)
        self.admin_id = self.store.add_user("Admin", "admin", is_admin=True)  # login sem '@', como o seed
        self.user_id = self.store.add_user("Maria", "maria@empresa.com")
        self.store.add_token(self.admin_id, ADMIN_TOKEN)
        self.store.add_token(self.user_id, USER_TOKEN)
        app = FastAPI()
        for router in (users_router, profiles_router, me_router):
            app.include_router(router)
        auth = AuthService(tokens, users, AsyncMock())
        app.dependency_overrides[get_auth_service] = lambda: auth
        app.dependency_overrides[get_user_repo] = lambda: users
        user_service = UserAdminService(self.db, users, tokens)
        profile_service = ProfileAdminService(self.db, profiles)
        app.dependency_overrides[get_user_admin_service] = lambda: user_service
        app.dependency_overrides[get_profile_admin_service] = lambda: profile_service
        self.app = app
        self.client = TestClient(app)

    def call(self, method, path, token=ADMIN_TOKEN, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.request(method, path, headers=headers, **kwargs)


@pytest.fixture
def env():
    return Env()


def _routes(app, prefix):
    """(MÉTODO, path) de toda rota sob `prefix`, via OpenAPI — independe de como o
    FastAPI guarda os routers incluídos em `app.routes`."""
    return [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith(prefix)
        for method in operations
    ]


def _admin_routes(app):
    return _routes(app, "/admin")


def _fill(path):
    return path.replace("{user_id}", str(uuid4())).replace("{token_id}", str(uuid4())).replace(
        "{profile_id}", str(uuid4())
    )


class TestAdminAuthorization:
    def test_there_are_admin_routes(self, env):
        assert len(_admin_routes(env.app)) >= 19

    def test_no_token_returns_401_on_every_admin_route(self, env):
        for method, path in _admin_routes(env.app):
            response = env.call(method, _fill(path), token=None, json={})
            assert response.status_code == 401, (method, path)
            assert response.json()["error"] == "unauthorized"
            assert response.headers["www-authenticate"] == "Bearer"

    def test_non_admin_returns_403_on_every_admin_route(self, env):
        for method, path in _admin_routes(env.app):
            response = env.call(method, _fill(path), token=USER_TOKEN, json={})
            assert response.status_code == 403, (method, path)
            assert response.json()["error"] == "forbidden"

    def test_invalid_token_returns_401(self, env):
        assert env.call("GET", "/admin/users", token="nope").status_code == 401

    def test_demoted_admin_loses_access_with_same_token(self, env):
        assert env.call("GET", "/admin/users").status_code == 200
        env.store.users[env.admin_id]["is_admin"] = False
        assert env.call("GET", "/admin/users").status_code == 403

    def test_blocked_admin_loses_access(self, env):
        env.store.users[env.admin_id]["is_blocked"] = True
        assert env.call("GET", "/admin/users").status_code == 401

    def test_me_accepts_non_admin(self, env):
        assert env.call("GET", "/me", token=USER_TOKEN).status_code == 200

    def test_me_requires_token(self, env):
        assert env.call("GET", "/me", token=None).status_code == 401


class TestPasswordPolicy:
    @pytest.mark.parametrize("password", ["Ab1!xy", "Senh@123", "Ação#123x", "A b1!c"])
    def test_valid(self, password):
        validate_password_policy(password)

    @pytest.mark.parametrize(
        "password",
        ["Ab1!x", "abc123", "abcdef1!", "ABCDEF1!", "Abcdef!!", "Abcdef12", "Abcde 12", "Aa1!" + "x" * 70],
    )
    def test_invalid(self, password):
        with pytest.raises(PasswordPolicyError):
            validate_password_policy(password)

    def test_72_byte_limit_counts_bytes(self):
        validate_password_policy("Aa1!" + "x" * 68)  # 72 bytes
        with pytest.raises(PasswordPolicyError):
            validate_password_policy("Aa1!" + "ç" * 35)  # 74 bytes, 39 caracteres


class TestHashPassword:
    @pytest.mark.asyncio
    async def test_hash_verifies_with_cost_12(self):
        hashed = await hash_password("Senh@123")
        assert hashed.startswith("$2b$12$")
        assert verify_password("Senh@123", hashed)
        assert not verify_password("outra", hashed)

    @pytest.mark.asyncio
    async def test_over_72_bytes_refused(self):
        with pytest.raises(PasswordPolicyError):
            await hash_password("x" * 73)


class TestUsersRoutes:
    def test_list_with_seed_login_and_pagination(self, env):
        body = env.call("GET", "/admin/users").json()
        assert body["total"] == 2 and body["limit"] == 50 and body["offset"] == 0
        assert {u["email"] for u in body["items"]} == {"admin", "maria@empresa.com"}
        page = env.call("GET", "/admin/users?limit=1&offset=1").json()
        assert len(page["items"]) == 1 and page["total"] == 2

    @pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1"])
    def test_pagination_bounds_422(self, env, query):
        assert env.call("GET", f"/admin/users?{query}").status_code == 422

    def test_filters(self, env):
        env.store.users[env.user_id]["is_blocked"] = True
        assert env.call("GET", "/admin/users?is_blocked=true").json()["total"] == 1
        assert env.call("GET", "/admin/users?q=mar").json()["total"] == 1
        pid = env.store.add_profile()
        env.store.user_profiles.add((env.user_id, pid))
        assert env.call("GET", f"/admin/users?profile_id={pid}").json()["total"] == 1

    def test_create_with_profiles_and_login(self, env):
        pid = env.store.add_profile()
        response = env.call("POST", "/admin/users", json={
            "name": "Novo", "email": " Novo@Empresa.com ", "password": GOOD_PASSWORD, "profile_ids": [str(pid)],
        })
        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "novo@empresa.com" and body["is_admin"] is False
        assert [p["id"] for p in body["profiles"]] == [str(pid)]
        assert body["created_by"] == "admin"
        assert "password" not in response.text and "hash" not in response.text
        stored = next(u for u in env.store.users.values() if u["external_id"] == "novo@empresa.com")
        assert verify_password(GOOD_PASSWORD, stored["password_hash"])

    def test_create_weak_password_400_and_nothing_saved(self, env):
        response = env.call("POST", "/admin/users", json={"name": "N", "email": "n@e.com", "password": "abc123"})
        assert response.status_code == 400 and response.json()["error"] == "invalid_password"
        assert len(env.store.users) == 2

    def test_create_duplicate_email_any_case_409(self, env):
        response = env.call("POST", "/admin/users", json={
            "name": "N", "email": "MARIA@empresa.com", "password": GOOD_PASSWORD})
        assert response.status_code == 409 and response.json()["error"] == "email_already_exists"

    def test_create_invalid_email_422(self, env):
        response = env.call("POST", "/admin/users", json={"name": "N", "email": "sem-arroba", "password": GOOD_PASSWORD})
        assert response.status_code == 422 and len(env.store.users) == 2

    def test_create_invalid_profile_rolls_back(self, env):
        ghost = uuid4()
        response = env.call("POST", "/admin/users", json={
            "name": "N", "email": "n@e.com", "password": GOOD_PASSWORD, "profile_ids": [str(ghost)]})
        assert response.status_code == 422
        assert response.json()["error"] == "invalid_reference" and str(ghost) in response.json()["message"]
        assert len(env.store.users) == 2

    def test_get_and_404(self, env):
        assert env.call("GET", f"/admin/users/{env.admin_id}").json()["email"] == "admin"
        response = env.call("GET", f"/admin/users/{uuid4()}")
        assert response.status_code == 404 and response.json()["error"] == "user_not_found"

    def test_get_counts_active_tokens(self, env):
        env.store.add_token(env.user_id, "t2")
        env.store.add_token(env.user_id, "t3", revoked=True)
        assert env.call("GET", f"/admin/users/{env.user_id}").json()["active_tokens"] == 2

    def test_patch_partial_keeps_seed_login(self, env):
        response = env.call("PATCH", f"/admin/users/{env.admin_id}", json={"name": "Outro"})
        assert response.status_code == 200
        assert response.json()["name"] == "Outro" and response.json()["email"] == "admin"

    def test_patch_email_duplicate_409_and_empty_422(self, env):
        assert env.call("PATCH", f"/admin/users/{env.admin_id}", json={"email": "maria@empresa.com"}).status_code == 409
        assert env.call("PATCH", f"/admin/users/{env.user_id}", json={}).status_code == 422

    def test_patch_can_promote(self, env):
        assert env.call("PATCH", f"/admin/users/{env.user_id}", json={"is_admin": True}).json()["is_admin"] is True

    def test_delete_without_history(self, env):
        pid = env.store.add_profile()
        env.store.user_profiles.add((env.user_id, pid))
        assert env.call("DELETE", f"/admin/users/{env.user_id}").status_code == 204
        assert env.user_id not in env.store.users and not env.store.user_profiles

    def test_delete_with_history_409(self, env):
        env.store.history_user_ids.add(env.user_id)
        response = env.call("DELETE", f"/admin/users/{env.user_id}")
        assert response.status_code == 409 and response.json()["error"] == "user_has_history"
        assert env.user_id in env.store.users

    def test_reset_password_revokes_tokens(self, env):
        env.store.add_token(env.user_id, "second")
        assert env.call("PUT", f"/admin/users/{env.user_id}/password", json={"password": GOOD_PASSWORD}).status_code == 204
        assert all(t["revoked_at"] for t in env.store.tokens.values() if t["user_id"] == env.user_id)
        assert env.call("GET", "/me", token=USER_TOKEN).status_code == 401
        assert verify_password(GOOD_PASSWORD, env.store.users[env.user_id]["password_hash"])

    def test_reset_password_weak_and_missing_user(self, env):
        assert env.call("PUT", f"/admin/users/{env.user_id}/password", json={"password": "abc123"}).status_code == 400
        assert env.call("PUT", f"/admin/users/{uuid4()}/password", json={"password": GOOD_PASSWORD}).status_code == 404

    def test_admin_resets_own_password_and_loses_token(self, env):
        assert env.call("PUT", f"/admin/users/{env.admin_id}/password", json={"password": GOOD_PASSWORD}).status_code == 204
        assert env.call("GET", "/admin/users").status_code == 401

    def test_block_and_unblock_keep_tokens(self, env):
        body = env.call("POST", f"/admin/users/{env.user_id}/block").json()
        assert body["is_blocked"] is True
        assert env.call("GET", "/me", token=USER_TOKEN).status_code == 401
        assert all(t["revoked_at"] is None for t in env.store.tokens.values() if t["user_id"] == env.user_id)
        assert env.call("POST", f"/admin/users/{env.user_id}/unblock").json()["is_blocked"] is False
        assert env.call("GET", "/me", token=USER_TOKEN).status_code == 200

    def test_set_profiles_replaces_and_validates(self, env):
        p1, p2 = env.store.add_profile("A"), env.store.add_profile("B")
        env.call("PUT", f"/admin/users/{env.user_id}/profiles", json={"profile_ids": [str(p1)]})
        body = env.call("PUT", f"/admin/users/{env.user_id}/profiles", json={"profile_ids": [str(p2), str(p2)]}).json()
        assert [p["id"] for p in body["profiles"]] == [str(p2)]
        response = env.call("PUT", f"/admin/users/{env.user_id}/profiles", json={"profile_ids": [str(uuid4())]})
        assert response.status_code == 422
        assert [p[1] for p in env.store.user_profiles] == [p2]  # nada mudou

    def test_tokens_list_never_exposes_hash(self, env):
        tid = env.store.add_token(env.user_id, "extra", revoked=True)
        response = env.call("GET", f"/admin/users/{env.user_id}/tokens")
        assert {t["id"] for t in response.json()} >= {str(tid)}
        assert "token_hash" not in response.text

    def test_revoke_one_token_and_foreign_token_404(self, env):
        tid = env.store.add_token(env.user_id, "extra")
        assert env.call("DELETE", f"/admin/users/{env.user_id}/tokens/{tid}").status_code == 204
        assert env.store.tokens[tid]["revoked_at"] is not None
        response = env.call("DELETE", f"/admin/users/{env.admin_id}/tokens/{tid}")
        assert response.status_code == 404 and response.json()["error"] == "token_not_found"
        assert env.call("DELETE", f"/admin/users/{uuid4()}/tokens/{tid}").json()["error"] == "user_not_found"

    def test_revoke_all_tokens(self, env):
        env.store.add_token(env.user_id, "extra")
        assert env.call("DELETE", f"/admin/users/{env.user_id}/tokens").json() == {"revoked": 2}


class TestUserProtections:
    def test_admin_cannot_block_delete_or_demote_self(self, env):
        for method, path, body in [
            ("POST", f"/admin/users/{env.admin_id}/block", None),
            ("DELETE", f"/admin/users/{env.admin_id}", None),
            ("PATCH", f"/admin/users/{env.admin_id}", {"is_admin": False}),
        ]:
            response = env.call(method, path, json=body)
            assert response.status_code == 409 and response.json()["error"] == "self_protected", path

    def test_last_admin_protected_on_race(self, env):
        # Simula a corrida: quando a verificação roda, o ator já deixou de ser admin ativo.
        env.store.users[env.admin_id]["is_blocked"] = True
        other = env.store.add_user("Outro", "outro@e.com", is_admin=True)
        env.store.users[env.admin_id]["is_blocked"] = False
        service = env.app.dependency_overrides[get_user_admin_service]()
        original = service._users.lock_active_admin_ids

        async def only_target(db):
            ids = await original(db)
            return ids - {env.admin_id}

        service._users.lock_active_admin_ids = only_target
        for method, path, body in [
            ("POST", f"/admin/users/{other}/block", None),
            ("DELETE", f"/admin/users/{other}", None),
            ("PATCH", f"/admin/users/{other}", {"is_admin": False}),
        ]:
            response = env.call(method, path, json=body)
            assert response.status_code == 409 and response.json()["error"] == "last_admin_protected", path
        assert env.store.users[other]["is_admin"] and not env.store.users[other]["is_blocked"]

    def test_admin_can_demote_another_admin(self, env):
        other = env.store.add_user("Outro", "outro@e.com", is_admin=True)
        assert env.call("PATCH", f"/admin/users/{other}", json={"is_admin": False}).status_code == 200


class TestProfilesRoutes:
    def test_crud(self, env):
        created = env.call("POST", "/admin/profiles", json={"name": "Financeiro", "description": "d"})
        assert created.status_code == 201
        pid = created.json()["id"]
        assert env.call("GET", f"/admin/profiles/{pid}").json()["description"] == "d"
        patched = env.call("PATCH", f"/admin/profiles/{pid}", json={"is_active": False}).json()
        assert patched["is_active"] is False and patched["name"] == "Financeiro"
        assert env.call("GET", "/admin/profiles?is_active=false").json()["total"] == 1
        assert env.call("DELETE", f"/admin/profiles/{pid}").status_code == 204
        assert env.call("GET", f"/admin/profiles/{pid}").json()["error"] == "profile_not_found"

    def test_duplicate_name_409(self, env):
        env.call("POST", "/admin/profiles", json={"name": "X"})
        response = env.call("POST", "/admin/profiles", json={"name": "X"})
        assert response.status_code == 409 and response.json()["error"] == "profile_name_already_exists"

    def test_patch_empty_422(self, env):
        pid = env.store.add_profile()
        assert env.call("PATCH", f"/admin/profiles/{pid}", json={}).status_code == 422

    def test_set_analyses_and_users(self, env):
        pid = env.store.add_profile()
        aid = env.store.add_analysis()
        body = env.call("PUT", f"/admin/profiles/{pid}/analyses", json={"analysis_ids": [str(aid), str(aid)]}).json()
        assert body["analyses_count"] == 1 and body["analyses"][0]["name"] == "Vendas"
        body = env.call("PUT", f"/admin/profiles/{pid}/users", json={"user_ids": [str(env.user_id)]}).json()
        assert body["users"][0]["email"] == "maria@empresa.com"

    def test_invalid_reference_422_and_rollback(self, env):
        pid = env.store.add_profile()
        aid = env.store.add_analysis()
        env.store.profile_analyses.add((pid, aid))
        ghost = uuid4()
        response = env.call("PUT", f"/admin/profiles/{pid}/analyses", json={"analysis_ids": [str(ghost)]})
        assert response.status_code == 422 and str(ghost) in response.json()["message"]
        assert env.store.profile_analyses == {(pid, aid)}
        assert env.call("PUT", f"/admin/profiles/{uuid4()}/users", json={"user_ids": []}).status_code == 404

    def test_delete_cascades(self, env):
        pid = env.store.add_profile()
        env.store.user_profiles.add((env.user_id, pid))
        env.store.profile_analyses.add((pid, env.store.add_analysis()))
        assert env.call("DELETE", f"/admin/profiles/{pid}").status_code == 204
        assert not env.store.user_profiles and not env.store.profile_analyses


class TestMeRoutes:
    def test_get_me(self, env):
        pid = env.store.add_profile()
        env.store.user_profiles.add((env.user_id, pid))
        body = env.call("GET", "/me", token=USER_TOKEN).json()
        assert body["email"] == "maria@empresa.com" and body["is_admin"] is False
        assert body["profiles"][0]["id"] == str(pid) and "password" not in str(body)

    def test_wrong_current_password_400(self, env):
        response = env.call("PUT", "/me/password", token=USER_TOKEN,
                            json={"current_password": "errada", "new_password": GOOD_PASSWORD})
        assert response.status_code == 400 and response.json()["error"] == "invalid_current_password"

    def test_weak_new_password_400(self, env):
        response = env.call("PUT", "/me/password", token=USER_TOKEN,
                            json={"current_password": "Senh@123", "new_password": "abc123"})
        assert response.status_code == 400 and response.json()["error"] == "invalid_password"

    def test_change_revokes_every_token(self, env):
        env.store.add_token(env.user_id, "another")
        response = env.call("PUT", "/me/password", token=USER_TOKEN,
                            json={"current_password": "Senh@123", "new_password": GOOD_PASSWORD})
        assert response.status_code == 204
        assert all(t["revoked_at"] for t in env.store.tokens.values() if t["user_id"] == env.user_id)
        assert env.call("GET", "/me", token=USER_TOKEN).status_code == 401
        assert verify_password(GOOD_PASSWORD, env.store.users[env.user_id]["password_hash"])


class TestSerializationAndLogs:
    def test_no_secret_fields_in_any_response(self, env):
        env.store.add_token(env.user_id, "x")
        for path in ("/admin/users", f"/admin/users/{env.user_id}", f"/admin/users/{env.user_id}/tokens", "/admin/profiles"):
            text = env.call("GET", path).text
            assert "password_hash" not in text and "token_hash" not in text, path

    def test_admin_action_log_has_no_secrets(self, env, caplog):
        with caplog.at_level(logging.INFO):
            env.call("POST", "/admin/users", json={"name": "N", "email": "log@e.com", "password": GOOD_PASSWORD})
            env.call("GET", "/admin/users", token="bad-token-value")
        text = caplog.text
        assert "admin_action" in text and "auth_failed" in text
        assert GOOD_PASSWORD not in text and "log@e.com" not in text and "bad-token-value" not in text


class TestCors:
    def test_preflight_allows_put_and_patch(self):
        from main import app as real_app

        cors = next(m for m in real_app.user_middleware if m.cls is CORSMiddleware)
        assert {"PUT", "PATCH"} <= set(cors.kwargs["allow_methods"])


class TestMainWiring:
    def test_real_app_registers_admin_routers(self):
        from main import app as real_app

        paths = set(real_app.openapi()["paths"])
        assert {"/admin/users", "/admin/profiles", "/me", "/me/password"} <= paths
