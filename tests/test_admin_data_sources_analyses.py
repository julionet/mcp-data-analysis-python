"""API administrativa /admin/data-sources e /admin/analyses — F24 §6.1.

FastAPI mínimo (sem lifespan/banco) com os serviços reais sobre repositórios em memória.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import InvalidToken
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters import oracle, sqlserver
from adapters.factory import AdapterFactory
from routes.admin_analyses import router as analyses_router
from routes.admin_data_sources import router as data_sources_router
from routes.auth import get_auth_service
from routes.dependencies import (
    get_analysis_admin_service,
    get_data_source_admin_service,
    get_user_repo,
)
from schemas.admin import InvalidConnectionConfigError, UnsupportedDataSourceTypeError
from schemas.data_source_types import DATA_SOURCE_TYPES, validate_connection_config
from schemas.sql_validation import extract_placeholders
from security.crypto import decrypt_password
from services.analysis_admin_service import AnalysisAdminService, validate_analysis_definition
from services.analysis_service import AnalysisService
from services.auth_service import AuthService
from services.data_source_admin_service import DataSourceAdminService
from tests.admin_fakes import (
    FakeAnalysisRepo,
    FakeDataSourceRepo,
    FakeDb,
    FakeProfileRepo,
    FakeTokenRepo,
    FakeUserRepo,
    Store,
)

ADMIN_TOKEN = "admin-token"
USER_TOKEN = "user-token"

PG_CONFIG = dict(host="db", port=5432, database="vendas", user="ro", password="s3gredo!")


class Invalidator:
    def __init__(self) -> None:
        self.calls: list = []
        self.fail = False

    async def invalidate_data_source(self, ds_id) -> None:
        self.calls.append(ds_id)
        if self.fail:
            raise RuntimeError("boom")


class Env:
    def __init__(self) -> None:
        self.store = Store()
        self.db = FakeDb(self.store)
        users, tokens = FakeUserRepo(self.store), FakeTokenRepo(self.store)
        self.admin_id = self.store.add_user("Admin", "admin", is_admin=True)
        self.user_id = self.store.add_user("Maria", "maria@empresa.com")
        self.store.add_token(self.admin_id, ADMIN_TOKEN)
        self.store.add_token(self.user_id, USER_TOKEN)
        self.pool = Invalidator()
        self.ds_service = DataSourceAdminService(
            self.db, FakeDataSourceRepo(self.store), self.pool, users
        )
        self.an_service = AnalysisAdminService(
            self.db, FakeAnalysisRepo(self.store), FakeDataSourceRepo(self.store),
            FakeProfileRepo(self.store), users,
        )
        app = FastAPI()
        for router in (data_sources_router, analyses_router):
            app.include_router(router)
        auth = AuthService(tokens, users, AsyncMock())
        app.dependency_overrides[get_auth_service] = lambda: auth
        app.dependency_overrides[get_user_repo] = lambda: users
        app.dependency_overrides[get_data_source_admin_service] = lambda: self.ds_service
        app.dependency_overrides[get_analysis_admin_service] = lambda: self.an_service
        self.app = app
        self.client = TestClient(app)

    def call(self, method, path, token=ADMIN_TOKEN, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.request(method, path, headers=headers, **kwargs)

    def analysis_body(self, ds_id, **overrides):
        body = {
            "name": "vendas_por_regiao", "data_source_id": str(ds_id),
            "parameters": {"data_inicial": {"type": "date", "required": True}},
            "step": {"sql": "SELECT * FROM v WHERE d >= :data_inicial", "params": ["data_inicial"]},
        }
        return {**body, **overrides}


@pytest.fixture
def env():
    return Env()


def _fill(path):
    return path.replace("{data_source_id}", str(uuid4())).replace("{analysis_id}", str(uuid4()))


def _routes(app):
    return [(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops]


class TestSweepAuthorization:
    def test_there_are_routes(self, env):
        assert len(_routes(env.app)) >= 16

    def test_401_without_token_on_every_route(self, env):
        for method, path in _routes(env.app):
            r = env.call(method, _fill(path), token=None, json={})
            assert r.status_code == 401 and r.json()["error"] == "unauthorized", (method, path)

    def test_403_for_non_admin_on_every_route(self, env):
        for method, path in _routes(env.app):
            r = env.call(method, _fill(path), token=USER_TOKEN, json={})
            assert r.status_code == 403 and r.json()["error"] == "forbidden", (method, path)


class TestDataSourceTypes:
    def test_types_match_adapter_factory(self):
        assert set(DATA_SOURCE_TYPES) == set(AdapterFactory._adapters)

    def test_defaults_match_adapters(self):
        assert DATA_SOURCE_TYPES["sqlserver"].optional["port"] == sqlserver.DEFAULT_PORT
        assert DATA_SOURCE_TYPES["sqlserver"].optional["driver"] == sqlserver.DEFAULT_DRIVER
        assert DATA_SOURCE_TYPES["sqlserver"].optional["sslmode"] == sqlserver.DEFAULT_SSLMODE
        assert DATA_SOURCE_TYPES["oracle"].optional["port"] == oracle.DEFAULT_PORT

    def test_endpoint_lists_types(self, env):
        body = env.call("GET", "/admin/data-sources/types").json()
        assert {t["type"] for t in body} == set(DATA_SOURCE_TYPES)
        oracle_t = next(t for t in body if t["type"] == "oracle")
        assert oracle_t["one_of"] == [["service_name", "sid"]]

    @pytest.mark.parametrize("type_,config", [
        ("postgresql", PG_CONFIG),
        ("postgresql", {**PG_CONFIG, "pool_min_size": 1, "pool_max_size": 5}),
        ("mysql", dict(host="h", database="d", user="u", password="p")),
        ("sqlserver", dict(host="h", database="d", user="u", password="p", sslmode="verify-full", port=1433)),
        ("oracle", dict(host="h", user="u", password="p", service_name="ORCL")),
        ("oracle", dict(host="h", user="u", password="p", sid="XE", port=1521)),
    ])
    def test_valid_configs(self, type_, config):
        validate_connection_config(type_, config)

    @pytest.mark.parametrize("type_,config", [
        ("postgresql", {k: v for k, v in PG_CONFIG.items() if k != "port"}),
        ("postgresql", {**PG_CONFIG, "passwrd": "x"}),
        ("postgresql", {**PG_CONFIG, "port": 70000}),
        ("postgresql", {**PG_CONFIG, "port": "5432"}),
        ("postgresql", {**PG_CONFIG, "port": True}),
        ("postgresql", {**PG_CONFIG, "host": "  "}),
        ("postgresql", {**PG_CONFIG, "pool_min_size": 5, "pool_max_size": 2}),
        ("postgresql", {**PG_CONFIG, "pool_min_size": 0}),
        ("postgresql", {**PG_CONFIG, "pool_max_size": 1}),  # min efetivo vem do .env (padrão 10)
        ("mysql", dict(host="h", database="d", user="u", password="")),
        ("sqlserver", dict(host="h", database="d", user="u", password="p", sslmode="disable")),
        ("oracle", dict(host="h", user="u", password="p")),
        ("oracle", dict(host="h", user="u", password="p", service_name="a", sid="b")),
    ])
    def test_invalid_configs(self, type_, config):
        with pytest.raises(InvalidConnectionConfigError):
            validate_connection_config(type_, config)

    def test_unsupported_type(self):
        with pytest.raises(UnsupportedDataSourceTypeError):
            validate_connection_config("mongodb", {})


class TestDataSourceRoutes:
    def create(self, env, **overrides):
        body = {"name": "vendas_db", "type": "postgresql", "connection_config": dict(PG_CONFIG), **overrides}
        return env.call("POST", "/admin/data-sources", json=body)

    def test_create_encrypts_and_never_returns_password(self, env):
        r = self.create(env)
        assert r.status_code == 201
        body = r.json()
        assert "password" not in body["connection_config"] and body["has_password"] is True
        assert "s3gredo!" not in r.text
        stored = next(iter(env.store.data_sources.values()))["connection_config"]["password"]
        assert stored != "s3gredo!" and decrypt_password(stored) == "s3gredo!"
        assert body["created_by"] == "admin"

    def test_create_duplicate_name_409(self, env):
        assert self.create(env).status_code == 201
        r = self.create(env)
        assert r.status_code == 409 and r.json()["error"] == "data_source_name_already_exists"

    def test_create_invalid_config_422_nothing_saved(self, env):
        r = self.create(env, connection_config={"host": "h"})
        assert r.status_code == 422 and r.json()["error"] == "invalid_connection_config"
        assert not env.store.data_sources

    def test_create_unsupported_type_422(self, env):
        r = self.create(env, type="mongodb")
        assert r.status_code == 422 and r.json()["error"] == "unsupported_data_source_type"

    def test_list_filters_and_pagination(self, env):
        env.store.add_data_source("a_pg")
        env.store.add_data_source("b_my", "mysql", is_active=False)
        body = env.call("GET", "/admin/data-sources").json()
        assert body["total"] == 2 and body["limit"] == 50
        assert env.call("GET", "/admin/data-sources?type=mysql").json()["total"] == 1
        assert env.call("GET", "/admin/data-sources?is_active=false").json()["total"] == 1
        assert env.call("GET", "/admin/data-sources?q=a_p").json()["total"] == 1
        assert len(env.call("GET", "/admin/data-sources?limit=1&offset=1").json()["items"]) == 1
        assert env.call("GET", "/admin/data-sources?limit=201").status_code == 422

    def test_get_detail_lists_analyses_without_password(self, env):
        ds = env.store.add_data_source()
        env.store.add_full_analysis(ds_id=ds)
        r = env.call("GET", f"/admin/data-sources/{ds}")
        assert r.status_code == 200 and r.json()["analyses_count"] == 1
        assert len(r.json()["analyses"]) == 1 and "password" not in r.json()["connection_config"]
        assert env.call("GET", f"/admin/data-sources/{uuid4()}").status_code == 404

    def test_patch_without_password_keeps_cipher(self, env):
        ds = env.store.add_data_source()
        before = env.store.data_sources[ds]["connection_config"]["password"]
        r = env.call("PATCH", f"/admin/data-sources/{ds}", json={"connection_config": {"host": "novo"}})
        assert r.status_code == 200 and r.json()["connection_config"]["host"] == "novo"
        cfg = env.store.data_sources[ds]["connection_config"]
        assert cfg["password"] == before and cfg["database"] == "d"
        assert "segredo" not in r.text

    def test_patch_password_reencrypts(self, env):
        ds = env.store.add_data_source()
        env.call("PATCH", f"/admin/data-sources/{ds}", json={"connection_config": {"password": "outra"}})
        assert decrypt_password(env.store.data_sources[ds]["connection_config"]["password"]) == "outra"

    def test_patch_null_removes_optional_but_not_required(self, env):
        ds = env.store.add_data_source(type_="mysql", config=dict(host="h", database="d", user="u",
                                                                  password="x", port=3307))
        r = env.call("PATCH", f"/admin/data-sources/{ds}", json={"connection_config": {"port": None}})
        assert r.status_code == 200 and "port" not in env.store.data_sources[ds]["connection_config"]
        r = env.call("PATCH", f"/admin/data-sources/{ds}", json={"connection_config": {"host": None}})
        assert r.status_code == 422 and r.json()["error"] == "invalid_connection_config"

    def test_patch_unknown_key_and_type_not_alterable(self, env):
        ds = env.store.add_data_source()
        r = env.call("PATCH", f"/admin/data-sources/{ds}", json={"connection_config": {"passwrd": "x"}})
        assert r.status_code == 422 and r.json()["error"] == "invalid_connection_config"
        r = env.call("PATCH", f"/admin/data-sources/{ds}", json={"type": "mysql"})
        assert r.status_code == 422  # corpo sem campo alterável
        assert env.store.data_sources[ds]["type"] == "postgresql"

    def test_patch_duplicate_name_and_empty_body(self, env):
        env.store.add_data_source("a")
        b = env.store.add_data_source("b")
        r = env.call("PATCH", f"/admin/data-sources/{b}", json={"name": "a"})
        assert r.status_code == 409 and r.json()["error"] == "data_source_name_already_exists"
        assert env.call("PATCH", f"/admin/data-sources/{b}", json={}).status_code == 422
        assert env.call("PATCH", f"/admin/data-sources/{uuid4()}", json={"name": "x"}).status_code == 404

    def test_delete_with_analyses_409_without_204(self, env):
        ds = env.store.add_data_source()
        aid = env.store.add_full_analysis(ds_id=ds)
        r = env.call("DELETE", f"/admin/data-sources/{ds}")
        assert r.status_code == 409 and r.json()["error"] == "data_source_has_analyses"
        env.store.analyses[aid]["is_active"] = False  # inativa também conta
        assert env.call("DELETE", f"/admin/data-sources/{ds}").status_code == 409
        del env.store.analyses[aid]
        assert env.call("DELETE", f"/admin/data-sources/{ds}").status_code == 204
        assert env.pool.calls == [ds]
        assert env.call("DELETE", f"/admin/data-sources/{ds}").status_code == 404


class TestDataSourceSideEffects:
    def test_config_change_invalidates_pool_and_bumps_analyses(self, env):
        ds = env.store.add_data_source()
        aid = env.store.add_full_analysis(ds_id=ds)
        other = env.store.add_full_analysis("outra", ds_id=env.store.add_data_source("x"))
        before, other_before = env.store.analyses[aid]["updated_at"], env.store.analyses[other]["updated_at"]
        env.call("PATCH", f"/admin/data-sources/{ds}", json={"connection_config": {"host": "novo"}})
        assert env.pool.calls == [ds]
        assert env.store.analyses[aid]["updated_at"] > before
        assert env.store.analyses[other]["updated_at"] == other_before

    def test_is_active_change_invalidates_and_bumps(self, env):
        ds = env.store.add_data_source()
        aid = env.store.add_full_analysis(ds_id=ds)
        before = env.store.analyses[aid]["updated_at"]
        env.call("PATCH", f"/admin/data-sources/{ds}", json={"is_active": False})
        assert env.pool.calls == [ds] and env.store.analyses[aid]["updated_at"] > before

    def test_name_only_or_same_values_do_nothing(self, env):
        ds = env.store.add_data_source()
        aid = env.store.add_full_analysis(ds_id=ds)
        before = env.store.analyses[aid]["updated_at"]
        env.call("PATCH", f"/admin/data-sources/{ds}", json={"name": "renomeado"})
        env.call("PATCH", f"/admin/data-sources/{ds}", json={"is_active": True, "connection_config": {"host": "h"}})
        assert env.pool.calls == [] and env.store.analyses[aid]["updated_at"] == before

    def test_pool_failure_does_not_fail_the_request(self, env):
        env.pool.fail = True
        ds = env.store.add_data_source()
        r = env.call("PATCH", f"/admin/data-sources/{ds}", json={"is_active": False})
        assert r.status_code == 200 and env.store.data_sources[ds]["is_active"] is False


def _adapter(connect=None, test=True, timeout=False, transient=False):
    adapter = MagicMock()
    adapter.connect = AsyncMock(side_effect=connect)
    adapter.test_connection = AsyncMock(return_value=test)
    adapter.disconnect = AsyncMock()
    adapter.is_timeout_error = MagicMock(return_value=timeout)
    adapter.is_transient_error = MagicMock(return_value=transient)
    return adapter


class TestConnectionTest:
    def run(self, env, adapter, path=None, **kwargs):
        ds = env.store.add_data_source()
        with patch.object(AdapterFactory, "create_adapter", return_value=adapter) as create:
            r = env.call("POST", path or f"/admin/data-sources/{ds}/test-connection", **kwargs)
        return r, create

    def test_ok_uses_decrypted_password_and_closes(self, env):
        adapter = _adapter()
        r, create = self.run(env, adapter)
        assert r.status_code == 200 and r.json()["ok"] is True
        assert create.call_args.args[1]["password"] == "segredo"
        adapter.disconnect.assert_awaited_once()

    def test_test_query_failed(self, env):
        adapter = _adapter(test=False)
        r, _ = self.run(env, adapter)
        assert r.json()["ok"] is False and "consulta de teste" in r.json()["message"]
        adapter.disconnect.assert_awaited_once()

    def test_connect_failure_categories_without_driver_text(self, env):
        secret = "host-interno.corp usuario ro"
        r, _ = self.run(env, _adapter(connect=OSError(secret), transient=True))
        body = r.json()
        assert body["ok"] is False and body["error_type"] == "OSError" and "indisponível" in body["message"]
        assert secret not in r.text
        r, _ = self.run(env, _adapter(connect=RuntimeError(secret)))
        assert "credenciais" in r.json()["message"] and secret not in r.text
        r, _ = self.run(env, _adapter(connect=RuntimeError(secret), timeout=True))
        assert "Tempo esgotado" in r.json()["message"]

    def test_timeout_via_wait_for_and_adapter_closed(self, env):
        async def hang():
            await asyncio.sleep(5)

        adapter = _adapter(connect=hang)
        with patch("services.data_source_admin_service.TEST_CONNECTION_TIMEOUT_SECONDS", 0.05):
            r, _ = self.run(env, adapter)
        assert r.json()["ok"] is False and "Tempo esgotado" in r.json()["message"]
        adapter.disconnect.assert_awaited_once()

    def test_inactive_data_source_can_be_tested(self, env):
        ds = env.store.add_data_source(is_active=False)
        with patch.object(AdapterFactory, "create_adapter", return_value=_adapter()):
            assert env.call("POST", f"/admin/data-sources/{ds}/test-connection").json()["ok"] is True

    def test_undecryptable_password(self, env):
        ds = env.store.add_data_source()
        env.store.data_sources[ds]["connection_config"]["password"] = "lixo"
        r = env.call("POST", f"/admin/data-sources/{ds}/test-connection")
        assert r.status_code == 200 and r.json()["ok"] is False and "FERNET_KEY" in r.json()["message"]

    def test_unknown_data_source_404(self, env):
        assert env.call("POST", f"/admin/data-sources/{uuid4()}/test-connection").status_code == 404

    def test_preview_tests_body_without_saving(self, env):
        adapter = _adapter()
        with patch.object(AdapterFactory, "create_adapter", return_value=adapter) as create:
            r = env.call("POST", "/admin/data-sources/test-connection",
                         json={"type": "postgresql", "connection_config": dict(PG_CONFIG)})
        assert r.json()["ok"] is True and create.call_args.args[1]["password"] == "s3gredo!"
        assert not env.store.data_sources
        r = env.call("POST", "/admin/data-sources/test-connection",
                     json={"type": "postgresql", "connection_config": {"host": "h"}})
        assert r.status_code == 422 and r.json()["error"] == "invalid_connection_config"

    def test_no_secrets_in_logs(self, env, caplog):
        caplog.set_level(logging.DEBUG)
        self.run(env, _adapter(connect=RuntimeError("falha com segredo na DSN")))
        assert "segredo" not in caplog.text.replace("falha com segredo na DSN", "")  # só a senha mascarada
        assert "***" in caplog.text


class TestAnalysisServiceInvalidation:
    def make(self):
        return AnalysisService(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_removes_and_disconnects(self):
        service, ds_id, adapter = self.make(), uuid4(), AsyncMock()
        service._adapters[ds_id] = adapter
        await service.invalidate_data_source(ds_id)
        assert ds_id not in service._adapters
        adapter.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_idempotent_and_disconnect_error_logged(self):
        service, ds_id = self.make(), uuid4()
        await service.invalidate_data_source(ds_id)  # inexistente: nada
        adapter = AsyncMock()
        adapter.disconnect.side_effect = RuntimeError("x")
        service._adapters[ds_id] = adapter
        await service.invalidate_data_source(ds_id)
        assert ds_id not in service._adapters


class TestExtractPlaceholders:
    def test_ignores_literals_comments_casts_and_quotes(self):
        sql = "SELECT a::int, ':x', \"y:z\" FROM t WHERE d >= :ini AND r = :reg AND d <= :ini -- :nope\n/* :nada */"
        assert extract_placeholders(sql) == ["ini", "reg"]

    def test_none(self):
        assert extract_placeholders("SELECT 1") == []


def _ds(active=True):
    from repositories.data_source_repo import DataSource

    return DataSource(uuid4(), "ds", "postgresql", {}, active)


def _check(**kw):
    base = dict(parameters={"a": {"type": "integer", "required": True}}, cache_frequency="daily",
                sql="SELECT 1 WHERE x = :a", step_params=["a"], data_source=_ds())
    errors, warnings = validate_analysis_definition(**{**base, **kw})
    return {e.code for e in errors}, {w.code for w in warnings}


class TestAnalysisDefinition:
    def test_valid(self):
        assert _check() == (set(), set())

    @pytest.mark.parametrize("kw,code", [
        (dict(parameters={"a": {"type": "xpto"}}), "invalid_parameters_schema"),
        (dict(parameters={"a": "texto"}), "invalid_parameters_schema"),
        (dict(parameters=["a"]), "invalid_parameters_schema"),
        (dict(cache_frequency="monthly"), "invalid_cache_frequency"),
        (dict(sql=None, step_params=None), "missing_step"),
        (dict(sql="DELETE FROM t WHERE x = :a"), "sql_not_allowed"),
        (dict(sql="SELECT 1 WHERE x = :a;"), "sql_not_allowed"),
        (dict(step_params=["a", "b"], sql="SELECT :a, :b"), "unknown_step_param"),
        (dict(sql="SELECT :a, :b"), "placeholder_not_declared"),
        (dict(sql="SELECT 1"), "param_not_in_sql"),
        (dict(step_params=["a", "a"]), "duplicate_step_param"),
        (dict(data_source=None), "data_source_not_found"),
    ])
    def test_errors(self, kw, code):
        assert code in _check(**kw)[0]

    def test_warnings(self):
        assert _check(data_source=_ds(active=False)) == (set(), {"data_source_inactive"})
        assert _check(parameters={"a": {"type": "integer"}, "b": {"type": "string"}})[1] == {"parameter_not_used"}


class TestAnalysisRoutes:
    def make_ds(self, env, **kw):
        return env.store.add_data_source(**kw)

    def test_create_full_in_one_go(self, env):
        ds = self.make_ds(env)
        pid = env.store.add_profile()
        r = env.call("POST", "/admin/analyses", json=env.analysis_body(ds, profile_ids=[str(pid), str(pid)]))
        assert r.status_code == 201
        body = r.json()
        assert body["step"]["step_order"] == 1 and body["step"]["params"] == ["data_inicial"]
        assert body["cache_frequency"] == "daily" and body["is_active"] is True
        assert [p["id"] for p in body["profiles"]] == [str(pid)] and body["created_by"] == "admin"
        assert body["data_source_name"] == "vendas_db"
        assert len(env.store.steps) == 1 and len(env.store.profile_analyses) == 1

    def test_create_links_nothing_beyond_profile_ids(self, env):
        ds = self.make_ds(env)
        env.store.add_profile("admin")
        r = env.call("POST", "/admin/analyses", json=env.analysis_body(ds))
        assert r.status_code == 201 and r.json()["profiles"] == [] and not env.store.profile_analyses

    def test_create_invalid_definition_422_nothing_saved(self, env):
        ds = self.make_ds(env)
        for step in (
            {"sql": "INSERT INTO t VALUES (:data_inicial)", "params": ["data_inicial"]},
            {"sql": "SELECT :data_inicial, :outro", "params": ["data_inicial"]},
            {"sql": "SELECT 1", "params": ["data_inicial"]},
            {"sql": "SELECT :data_inicial", "params": ["data_inicial", "fora"]},
        ):
            r = env.call("POST", "/admin/analyses", json=env.analysis_body(ds, step=step))
            assert r.status_code == 422 and r.json()["error"] == "invalid_analysis_definition", step
        r = env.call("POST", "/admin/analyses", json=env.analysis_body(ds, cache_frequency="monthly"))
        assert r.status_code == 422
        r = env.call("POST", "/admin/analyses", json=env.analysis_body(ds, parameters={"x": {"type": "zzz"}}))
        assert r.status_code == 422
        assert not env.store.analyses and not env.store.steps

    def test_create_invalid_reference_rolls_back(self, env):
        ds = self.make_ds(env)
        ghost = uuid4()
        r = env.call("POST", "/admin/analyses", json=env.analysis_body(ds, profile_ids=[str(ghost)]))
        assert r.status_code == 422 and r.json()["error"] == "invalid_reference" and str(ghost) in r.json()["message"]
        r = env.call("POST", "/admin/analyses", json=env.analysis_body(ghost))
        assert r.status_code == 422 and r.json()["error"] == "invalid_reference"
        assert not env.store.analyses and not env.store.steps

    def test_rollback_after_partial_write(self, env):
        ds = self.make_ds(env)
        repo = env.an_service._analyses
        with patch.object(repo, "replace_profiles", side_effect=RuntimeError("falha")):
            with pytest.raises(RuntimeError):
                env.client.post("/admin/analyses", json=env.analysis_body(ds),
                                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
        assert not env.store.analyses and not env.store.steps

    def test_create_duplicate_name_409(self, env):
        ds = self.make_ds(env)
        assert env.call("POST", "/admin/analyses", json=env.analysis_body(ds)).status_code == 201
        r = env.call("POST", "/admin/analyses", json=env.analysis_body(ds))
        assert r.status_code == 409 and r.json()["error"] == "analysis_name_already_exists"

    def test_list_includes_inactive_filters_and_pagination(self, env):
        ds = self.make_ds(env)
        a = env.store.add_full_analysis("ativa", ds_id=ds)
        b = env.store.add_full_analysis("inativa", ds_id=env.store.add_data_source("outro"))
        env.store.analyses[b]["is_active"] = False
        body = env.call("GET", "/admin/analyses").json()
        assert body["total"] == 2 and body["limit"] == 50
        assert env.call("GET", "/admin/analyses?is_active=false").json()["items"][0]["id"] == str(b)
        assert env.call("GET", f"/admin/analyses?data_source_id={ds}").json()["items"][0]["id"] == str(a)
        assert env.call("GET", "/admin/analyses?q=inat").json()["total"] == 1
        assert len(env.call("GET", "/admin/analyses?limit=1").json()["items"]) == 1
        assert env.call("GET", "/admin/analyses?limit=0").status_code == 422

    def test_get_detail_and_404(self, env):
        aid = env.store.add_full_analysis(ds_id=self.make_ds(env))
        body = env.call("GET", f"/admin/analyses/{aid}").json()
        assert body["step"]["sql"].startswith("SELECT") and body["parameters"]["a"]["type"] == "integer"
        assert env.call("GET", f"/admin/analyses/{uuid4()}").status_code == 404

    def test_get_legacy_without_step(self, env):
        aid = env.store.add_full_analysis(ds_id=self.make_ds(env), with_step=False)
        assert env.call("GET", f"/admin/analyses/{aid}").json()["step"] is None

    def test_patch_partial_merges_step_and_replaces_parameters(self, env):
        aid = env.store.add_full_analysis(ds_id=self.make_ds(env))
        r = env.call("PATCH", f"/admin/analyses/{aid}",
                     json={"step": {"sql": "SELECT 2 WHERE y = :a"}, "description": "nova"})
        assert r.status_code == 200
        step = next(iter(env.store.steps.values()))["definition"]
        assert step == {"sql": "SELECT 2 WHERE y = :a", "params": ["a"]}
        assert r.json()["description"] == "nova"
        r = env.call("PATCH", f"/admin/analyses/{aid}",
                     json={"parameters": {"a": {"type": "integer"}, "b": {"type": "string"}}})
        assert r.status_code == 200 and set(env.store.analyses[aid]["parameters"]) == {"a", "b"}

    def test_patch_removing_used_parameter_422(self, env):
        aid = env.store.add_full_analysis(ds_id=self.make_ds(env))
        r = env.call("PATCH", f"/admin/analyses/{aid}", json={"parameters": {"z": {"type": "string"}}})
        assert r.status_code == 422 and r.json()["error"] == "invalid_analysis_definition"
        assert "a" in env.store.analyses[aid]["parameters"]

    def test_patch_rename_deactivate_legacy_inconsistent_still_works(self, env):
        aid = env.store.add_full_analysis(ds_id=self.make_ds(env), sql="SELECT :nao_declarado")
        r = env.call("PATCH", f"/admin/analyses/{aid}", json={"is_active": False, "name": "novo"})
        assert r.status_code == 200 and r.json()["is_active"] is False

    def test_patch_creates_missing_step_requires_sql(self, env):
        aid = env.store.add_full_analysis(ds_id=self.make_ds(env), with_step=False)
        r = env.call("PATCH", f"/admin/analyses/{aid}", json={"step": {"params": ["a"]}})
        assert r.status_code == 422
        r = env.call("PATCH", f"/admin/analyses/{aid}", json={"step": {"sql": "SELECT :a", "params": ["a"]}})
        assert r.status_code == 200 and len(env.store.steps) == 1

    def test_patch_data_source_must_exist_and_errors(self, env):
        aid = env.store.add_full_analysis(ds_id=self.make_ds(env))
        r = env.call("PATCH", f"/admin/analyses/{aid}", json={"data_source_id": str(uuid4())})
        assert r.status_code == 422 and r.json()["error"] == "invalid_reference"
        assert env.call("PATCH", f"/admin/analyses/{aid}", json={}).status_code == 422
        assert env.call("PATCH", f"/admin/analyses/{uuid4()}", json={"is_active": False}).status_code == 404
        env.store.add_full_analysis("outra", ds_id=self.make_ds(env, name="x"))
        r = env.call("PATCH", f"/admin/analyses/{aid}", json={"name": "outra"})
        assert r.status_code == 409 and r.json()["error"] == "analysis_name_already_exists"

    def test_delete_with_history_409_then_without_204(self, env):
        aid = env.store.add_full_analysis(ds_id=self.make_ds(env))
        pid = env.store.add_profile()
        env.store.profile_analyses.add((pid, aid))
        env.store.history_analysis_ids.add(aid)
        r = env.call("DELETE", f"/admin/analyses/{aid}")
        assert r.status_code == 409 and r.json()["error"] == "analysis_has_history"
        env.store.history_analysis_ids.clear()
        assert env.call("DELETE", f"/admin/analyses/{aid}").status_code == 204
        assert not env.store.steps and not env.store.profile_analyses
        assert env.call("DELETE", f"/admin/analyses/{aid}").status_code == 404

    def test_set_profiles(self, env):
        aid = env.store.add_full_analysis(ds_id=self.make_ds(env))
        p1, p2 = env.store.add_profile("p1"), env.store.add_profile("p2")
        r = env.call("PUT", f"/admin/analyses/{aid}/profiles", json={"profile_ids": [str(p1), str(p2), str(p1)]})
        assert r.status_code == 200 and len(r.json()["profiles"]) == 2
        r = env.call("PUT", f"/admin/analyses/{aid}/profiles", json={"profile_ids": [str(p2)]})
        assert [p["id"] for p in r.json()["profiles"]] == [str(p2)]
        r = env.call("PUT", f"/admin/analyses/{aid}/profiles", json={"profile_ids": [str(uuid4())]})
        assert r.status_code == 422 and r.json()["error"] == "invalid_reference"
        assert len(env.store.profile_analyses) == 1  # nada mudou
        assert env.call("PUT", f"/admin/analyses/{uuid4()}/profiles", json={"profile_ids": []}).status_code == 404


class TestAnalysisCache:
    def test_patch_bumps_updated_at_even_when_only_step_changes(self, env):
        aid = env.store.add_full_analysis(ds_id=env.store.add_data_source())
        before = env.store.analyses[aid]["updated_at"]
        env.call("PATCH", f"/admin/analyses/{aid}", json={"step": {"sql": "SELECT 3 WHERE z = :a"}})
        assert env.store.analyses[aid]["updated_at"] > before

    def test_set_profiles_does_not_bump(self, env):
        aid = env.store.add_full_analysis(ds_id=env.store.add_data_source())
        before = env.store.analyses[aid]["updated_at"]
        env.call("PUT", f"/admin/analyses/{aid}/profiles", json={"profile_ids": []})
        assert env.store.analyses[aid]["updated_at"] == before

    def test_invalidate_bumps_and_404(self, env):
        aid = env.store.add_full_analysis(ds_id=env.store.add_data_source())
        before = env.store.analyses[aid]["updated_at"]
        r = env.call("POST", f"/admin/analyses/{aid}/cache/invalidate")
        assert r.status_code == 200 and r.json()["invalidated"] is True
        assert env.store.analyses[aid]["updated_at"] > before
        assert env.call("POST", f"/admin/analyses/{uuid4()}/cache/invalidate").status_code == 404

    def test_cache_key_changes_after_update(self, env):
        from services.cache_service import CacheService

        cache = CacheService(MagicMock(), 100, 100)
        aid = env.store.add_full_analysis(ds_id=env.store.add_data_source())
        k1 = cache.build_key(aid, env.store.analyses[aid]["updated_at"], {"a": 1})
        env.call("POST", f"/admin/analyses/{aid}/cache/invalidate")
        assert cache.build_key(aid, env.store.analyses[aid]["updated_at"], {"a": 1}) != k1


class TestValidateEndpoint:
    def test_legacy_inconsistent_is_reported_statically(self, env):
        ds = env.store.add_data_source(is_active=False)
        aid = env.store.add_full_analysis(ds_id=ds, sql="SELECT :a, :b")
        with patch.object(AdapterFactory, "create_adapter") as create:
            r = env.call("POST", f"/admin/analyses/{aid}/validate")
        create.assert_not_called()
        body = r.json()
        assert r.status_code == 200 and body["valid"] is False
        assert [e["code"] for e in body["errors"]] == ["placeholder_not_declared"]
        assert [w["code"] for w in body["warnings"]] == ["data_source_inactive"]

    def test_valid_with_warning_only(self, env):
        aid = env.store.add_full_analysis(ds_id=env.store.add_data_source(is_active=False))
        body = env.call("POST", f"/admin/analyses/{aid}/validate").json()
        assert body["valid"] is True and body["errors"] == []

    def test_no_step_and_404(self, env):
        aid = env.store.add_full_analysis(ds_id=env.store.add_data_source(), with_step=False)
        body = env.call("POST", f"/admin/analyses/{aid}/validate").json()
        assert body["valid"] is False and body["errors"][0]["code"] == "missing_step"
        assert env.call("POST", f"/admin/analyses/{uuid4()}/validate").status_code == 404


class TestNoSecretsInLogs:
    def test_admin_action_logs_have_no_password_or_sql(self, env, caplog):
        caplog.set_level(logging.INFO)
        ds = env.call("POST", "/admin/data-sources", json={
            "name": "x", "type": "postgresql", "connection_config": dict(PG_CONFIG)}).json()["id"]
        env.call("POST", "/admin/analyses", json=env.analysis_body(ds))
        env.call("PATCH", f"/admin/data-sources/{ds}", json={"connection_config": {"password": "Outra#Senha9"}})
        assert "admin_action" in caplog.text
        for secret in ("s3gredo!", "Outra#Senha9", "SELECT * FROM v", "connection_config"):
            assert secret not in caplog.text


class TestWiring:
    def test_real_app_registers_f24_routers_and_dependencies(self):
        from main import app as real_app

        paths = set(real_app.openapi()["paths"])
        assert {"/admin/data-sources", "/admin/data-sources/types", "/admin/analyses",
                "/admin/analyses/{analysis_id}/cache/invalidate"} <= paths

    def test_dependency_factories_build_services(self):
        assert isinstance(get_data_source_admin_service(), DataSourceAdminService)
        assert isinstance(get_analysis_admin_service(), AnalysisAdminService)

    def test_real_app_sweep_covers_new_routes(self, client):
        from main import app as real_app

        new = [(m.upper(), p) for p, ops in real_app.openapi()["paths"].items()
               if p.startswith(("/admin/data-sources", "/admin/analyses")) for m in ops]
        assert len(new) >= 16
        for method, path in new:
            r = client.request(method, _fill(path), json={})
            assert r.status_code == 401, (method, path)
