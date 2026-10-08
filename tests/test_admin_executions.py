"""API administrativa /admin/executions e /admin/analyses/{id}/executions — F25 §6.1.

FastAPI mínimo (sem lifespan/banco) com o serviço real sobre repositórios em memória.
"""

import logging
from datetime import datetime, timedelta
from typing import get_args
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.admin_analyses import router as analyses_router
from routes.admin_executions import router as executions_router
from routes.auth import get_auth_service
from routes.dependencies import get_execution_admin_service, get_user_repo
from schemas import exceptions
from schemas.admin import ExecutionErrorCode
from services.auth_service import AuthService
from services.execution_admin_service import ExecutionAdminService
from tests.admin_fakes import (
    FakeAnalysisRepo,
    FakeExecutionRepo,
    FakeTokenRepo,
    FakeUserRepo,
    Store,
)

ADMIN_TOKEN = "admin-token"
USER_TOKEN = "user-token"
NOW = datetime(2026, 10, 8, 12, 0)


class Env:
    def __init__(self) -> None:
        self.store = Store()
        users, tokens = FakeUserRepo(self.store), FakeTokenRepo(self.store)
        self.admin_id = self.store.add_user("Admin", "admin", is_admin=True)
        self.user_id = self.store.add_user("Maria", "maria@empresa.com")
        self.store.add_token(self.admin_id, ADMIN_TOKEN)
        self.store.add_token(self.user_id, USER_TOKEN)
        self.analysis_id = self.store.add_analysis("vendas")
        self.other_analysis_id = self.store.add_analysis("estoque", is_active=False)
        self.repo = FakeExecutionRepo(self.store)
        self.service = ExecutionAdminService(self.repo, FakeAnalysisRepo(self.store))
        app = FastAPI()
        for router in (executions_router, analyses_router):
            app.include_router(router)
        auth = AuthService(tokens, users, AsyncMock())
        app.dependency_overrides[get_auth_service] = lambda: auth
        app.dependency_overrides[get_user_repo] = lambda: users
        app.dependency_overrides[get_execution_admin_service] = lambda: self.service
        self.app = app
        self.client = TestClient(app)

    def call(self, method, path, token=ADMIN_TOKEN, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.request(method, path, headers=headers, **kwargs)

    def get(self, path, **kwargs):
        return self.call("GET", path, **kwargs)

    def add(self, **kwargs):
        kwargs.setdefault("analysis_id", self.analysis_id)
        return self.repo.add(**kwargs)


@pytest.fixture
def env():
    return Env()


def _routes(app):
    return [(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops
            if "execution" in p]


class TestSweepAuthorization:
    def test_routes_exist(self, env):
        assert len(_routes(env.app)) == 4

    def test_401_and_403_on_every_route(self, env):
        for method, path in _routes(env.app):
            url = path.replace("{execution_id}", str(uuid4())).replace("{analysis_id}", str(uuid4()))
            r = env.call(method, url, token=None)
            assert r.status_code == 401 and r.json()["error"] == "unauthorized", path
            r = env.call(method, url, token=USER_TOKEN)
            assert r.status_code == 403 and r.json()["error"] == "forbidden", path


class TestListExecutions:
    def test_empty(self, env):
        body = env.get("/admin/executions").json()
        assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}

    def test_item_shape_and_user_null(self, env):
        env.add(user_id=env.user_id, parameters={"regiao": "SP"}, time_ms=30, rows=7, size=900)
        env.add(analysis_id=env.other_analysis_id)  # pré-F12, análise inativa
        items = env.get("/admin/executions").json()["items"]
        assert len(items) == 2
        with_user = next(i for i in items if i["user"])
        assert with_user["user"] == {"id": str(env.user_id), "name": "Maria", "email": "maria@empresa.com"}
        assert with_user["analysis"] == {"id": str(env.analysis_id), "name": "vendas"}
        assert with_user["parameters"] == {"regiao": "SP"}
        assert (with_user["execution_time_ms"], with_user["rows_affected"], with_user["result_size_bytes"]) == (30, 7, 900)
        assert "error_message" not in with_user
        legacy = next(i for i in items if i["user"] is None)
        assert legacy["analysis"]["name"] == "estoque"

    def test_order_desc_and_tiebreak_by_id(self, env):
        old = env.add(executed_at=NOW - timedelta(hours=2))
        new = env.add(executed_at=NOW)
        ids = [i["id"] for i in env.get("/admin/executions").json()["items"]]
        assert ids == [str(new), str(old)]
        same = [env.add(executed_at=NOW - timedelta(days=1)) for _ in range(3)]
        tail = [i["id"] for i in env.get("/admin/executions").json()["items"]][2:]
        assert tail == sorted((str(i) for i in same), reverse=True)

    def test_pagination(self, env):
        for n in range(5):
            env.add(executed_at=NOW - timedelta(minutes=n))
        page = env.get("/admin/executions?limit=2&offset=2").json()
        assert (page["total"], page["limit"], page["offset"], len(page["items"])) == (5, 2, 2, 2)

    @pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1", "min_time_ms=-1", "analysis_id=x",
                                       "user_id=x", "status=failed", "error_code=NOPE", "from=ontem", "cached=talvez"])
    def test_invalid_query_is_422(self, env, query):
        assert env.get(f"/admin/executions?{query}").status_code == 422

    def test_filters_each_and_combined(self, env):
        a = env.add(user_id=env.user_id, status="error", error_code="QUERY_TIMEOUT", time_ms=5000,
                    executed_at=NOW - timedelta(hours=1))
        env.add(status="success", cached=True, time_ms=2)
        env.add(user_id=env.user_id, status="success", time_ms=200)
        env.add(analysis_id=env.other_analysis_id, status="timeout", error_code="QUERY_TIMEOUT", time_ms=9000)

        def ids(query):
            return {i["id"] for i in env.get(f"/admin/executions?{query}").json()["items"]}

        assert len(ids(f"analysis_id={env.analysis_id}")) == 3
        assert len(ids(f"user_id={env.user_id}")) == 2
        assert len(ids("status=error")) == 1
        assert len(ids("error_code=QUERY_TIMEOUT")) == 2
        assert len(ids("cached=true")) == 1 and len(ids("cached=false")) == 3
        assert len(ids("min_time_ms=1000")) == 2
        assert ids(f"user_id={env.user_id}&status=error&error_code=QUERY_TIMEOUT&min_time_ms=1000") == {str(a)}

    def test_from_inclusive_to_exclusive(self, env):
        boundary = env.add(executed_at=NOW)
        env.add(executed_at=NOW - timedelta(hours=1))
        iso = NOW.isoformat()
        assert [i["id"] for i in env.get(f"/admin/executions?from={iso}").json()["items"]] == [str(boundary)]
        assert env.get(f"/admin/executions?to={iso}").json()["total"] == 1

    def test_offset_datetime_is_converted_to_utc(self, env):
        env.add(executed_at=datetime(2026, 10, 8, 15, 0))
        assert env.get("/admin/executions", params={"from": "2026-10-08T12:00:00-03:00"}).json()["total"] == 1
        assert env.get("/admin/executions", params={"from": "2026-10-08T12:01:00-03:00"}).json()["total"] == 0

    def test_from_not_before_to_is_invalid_period(self, env):
        r = env.get("/admin/executions", params={"from": "2026-10-08T10:00:00", "to": "2026-10-08T10:00:00"})
        assert r.status_code == 422 and r.json()["error"] == "invalid_period"

    def test_unknown_analysis_or_user_gives_empty_page(self, env):
        env.add()
        assert env.get(f"/admin/executions?analysis_id={uuid4()}").json()["total"] == 0
        assert env.get(f"/admin/executions?user_id={uuid4()}").json()["total"] == 0


class TestParametersFilter:
    @pytest.fixture(autouse=True)
    def _rows(self, env):
        self.sp = env.add(parameters={"regiao": "SP", "ano": 2025})
        env.add(parameters={"regiao": "RJ"})
        env.add(parameters={"regiao": "SP", "ano": "2025"})

    def _get(self, env, raw):
        return env.get("/admin/executions", params={"parameters": raw})

    def test_object_matches_containment(self, env):
        assert self._get(env, '{"regiao":"SP"}').json()["total"] == 2

    def test_type_sensitive(self, env):
        body = self._get(env, '{"ano":2025}').json()
        assert [i["id"] for i in body["items"]] == [str(self.sp)]

    @pytest.mark.parametrize("raw", ["nao-json", "[1]", "{}", '"texto"', "123", '{"a":"' + "x" * 1000 + '"}'])
    def test_invalid_filter_is_422(self, env, raw):
        r = self._get(env, raw)
        assert r.status_code == 422 and r.json()["error"] == "invalid_parameters_filter"
        assert "nao-json" not in r.json()["message"]

    def test_error_does_not_run_query(self, env):
        self._get(env, "nao-json")
        assert env.repo.calls == []


class TestExecutionDetail:
    def test_detail_with_error_message(self, env):
        eid = env.add(user_id=env.user_id, status="error", error_code="QUERY_FAILED",
                      error_message="coluna inexistente", parameters={"a": 1})
        body = env.get(f"/admin/executions/{eid}").json()
        assert body["error_message"] == "coluna inexistente" and body["error_code"] == "QUERY_FAILED"
        assert body["parameters"] == {"a": 1} and body["user"]["email"] == "maria@empresa.com"
        assert "result_location" not in body

    def test_not_found(self, env):
        r = env.get(f"/admin/executions/{uuid4()}")
        assert r.status_code == 404 and r.json()["error"] == "execution_not_found"

    def test_malformed_id_is_422_not_stats(self, env):
        assert env.get("/admin/executions/xyz").status_code == 422


class TestAnalysisShortcut:
    def test_only_that_analysis(self, env):
        mine = env.add()
        env.add(analysis_id=env.other_analysis_id)
        body = env.get(f"/admin/analyses/{env.analysis_id}/executions").json()
        assert [i["id"] for i in body["items"]] == [str(mine)] and body["total"] == 1

    def test_accepts_filters_and_ignores_no_analysis_id_param(self, env):
        env.add(status="error", error_code="QUERY_FAILED", parameters={"r": "SP"})
        env.add(status="success", parameters={"r": "SP"})
        url = f"/admin/analyses/{env.analysis_id}/executions"
        assert env.get(f"{url}?status=error").json()["total"] == 1
        assert env.get(url, params={"parameters": '{"r":"SP"}'}).json()["total"] == 2
        assert env.get(f"{url}?analysis_id={env.other_analysis_id}").json()["total"] == 2

    def test_inactive_analysis_is_accepted(self, env):
        env.add(analysis_id=env.other_analysis_id)
        assert env.get(f"/admin/analyses/{env.other_analysis_id}/executions").json()["total"] == 1

    def test_unknown_analysis_is_404(self, env):
        r = env.get(f"/admin/analyses/{uuid4()}/executions")
        assert r.status_code == 404 and r.json()["error"] == "analysis_not_found"


class TestStats:
    def _populate(self, env):
        env.add(user_id=env.user_id, status="success", cached=False, time_ms=100)
        env.add(user_id=env.user_id, status="success", cached=False, time_ms=300)
        env.add(user_id=env.user_id, status="success", cached=True, time_ms=2)
        env.add(status="error", error_code="QUERY_FAILED", time_ms=5)
        env.add(analysis_id=env.other_analysis_id, status="timeout", error_code="QUERY_TIMEOUT", time_ms=9000)
        env.add(status="volume_exceeded")

    def test_counts_cache_time_and_tops(self, env):
        self._populate(env)
        body = env.get("/admin/executions/stats").json()
        assert body["total"] == 6
        assert body["by_status"] == {"success": 3, "volume_exceeded": 1, "error": 1, "timeout": 1}
        assert body["by_error_code"] == {"QUERY_FAILED": 1, "QUERY_TIMEOUT": 1}
        assert body["cache"] == {"hits": 1, "success": 3, "hit_rate": pytest.approx(1 / 3)}
        miss, hit = body["execution_time_ms"]["cache_miss"], body["execution_time_ms"]["cache_hit"]
        assert miss == {"count": 2, "avg": 200.0, "p95": pytest.approx(290.0), "max": 300}
        assert hit == {"count": 1, "avg": 2.0, "p95": 2.0, "max": 2}
        assert [(t["name"], t["count"]) for t in body["top_analyses"]] == [("vendas", 5), ("estoque", 1)]
        assert body["top_users"] == [{"user_id": str(env.user_id), "name": "Maria",
                                      "email": "maria@empresa.com", "count": 3}]

    def test_empty_period_is_zeroed_with_nulls(self, env):
        body = env.get("/admin/executions/stats").json()
        assert body["total"] == 0 and body["by_status"] == {"success": 0, "volume_exceeded": 0, "error": 0, "timeout": 0}
        assert body["by_error_code"] == {} and body["top_analyses"] == [] and body["top_users"] == []
        assert body["cache"] == {"hits": 0, "success": 0, "hit_rate": None}
        assert body["execution_time_ms"]["cache_miss"] == {"count": 0, "avg": None, "p95": None, "max": None}

    def test_default_period_is_last_7_days(self, env):
        env.add(executed_at=NOW - timedelta(days=6))
        env.add(executed_at=NOW - timedelta(days=8))
        body = env.get("/admin/executions/stats").json()
        assert body["total"] == 1
        assert body["period"] == {"from": (NOW - timedelta(days=7)).isoformat(), "to": NOW.isoformat()}

    def test_only_from_or_only_to(self, env):
        env.add(executed_at=NOW - timedelta(days=20))
        assert env.get("/admin/executions/stats", params={"from": (NOW - timedelta(days=30)).isoformat()}).json()["total"] == 1
        body = env.get("/admin/executions/stats", params={"to": (NOW - timedelta(days=10)).isoformat()}).json()
        assert body["total"] == 0
        assert body["period"]["from"] == (NOW - timedelta(days=17)).isoformat()

    def test_window_limit_366_days(self, env):
        ok = env.get("/admin/executions/stats", params={"from": (NOW - timedelta(days=366)).isoformat()})
        assert ok.status_code == 200
        too_long = env.get("/admin/executions/stats", params={"from": (NOW - timedelta(days=367)).isoformat()})
        assert too_long.status_code == 422 and too_long.json()["error"] == "invalid_period"

    def test_inverted_period(self, env):
        r = env.get("/admin/executions/stats", params={"from": "2026-10-08T10:00:00", "to": "2026-10-01T00:00:00"})
        assert r.status_code == 422 and r.json()["error"] == "invalid_period"

    def test_from_in_the_future_is_invalid_period(self, env):
        r = env.get("/admin/executions/stats", params={"from": (NOW + timedelta(days=1)).isoformat()})
        assert r.status_code == 422 and r.json()["error"] == "invalid_period"

    def test_filters_by_analysis_and_user(self, env):
        self._populate(env)
        by_analysis = env.get(f"/admin/executions/stats?analysis_id={env.other_analysis_id}").json()
        assert by_analysis["total"] == 1 and by_analysis["by_status"]["timeout"] == 1
        by_user = env.get(f"/admin/executions/stats?user_id={env.user_id}").json()
        assert by_user["total"] == 3

    def test_top_limit_and_validation(self, env):
        self._populate(env)
        assert len(env.get("/admin/executions/stats?top=1").json()["top_analyses"]) == 1
        for bad in ("top=0", "top=21", f"user_id=x"):
            assert env.get(f"/admin/executions/stats?{bad}").status_code == 422


class TestErrorCodeContract:
    def test_filter_enum_matches_f14_codes(self):
        declared = {
            getattr(cls, "error_code") for cls in vars(exceptions).values()
            if isinstance(cls, type) and hasattr(cls, "error_code")
        } | {exceptions.INTERNAL_ERROR_CODE}
        assert set(get_args(ExecutionErrorCode)) == declared


class TestReadOnlyAndNoSecrets:
    def test_only_read_methods_are_called(self, env):
        eid = env.add()
        for path in ("/admin/executions", "/admin/executions/stats", f"/admin/executions/{eid}",
                     f"/admin/analyses/{env.analysis_id}/executions"):
            assert env.get(path).status_code == 200
        assert set(env.repo.calls) <= {"search", "count", "get_detail", "resolve_period", "stats"}
        assert not any(hasattr(env.repo, name) for name in ("create", "update", "delete"))

    def test_write_methods_not_routed(self, env):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert env.call(method, "/admin/executions", json={}).status_code == 405

    def test_sensitive_data_never_logged(self, env, caplog):
        eid = env.add(parameters={"cpf": "123.456.789-00"}, status="error", error_code="QUERY_FAILED",
                      error_message="falha secreta-xyz")
        with caplog.at_level(logging.DEBUG):
            env.get(f"/admin/executions/{eid}")
            env.get("/admin/executions", params={"parameters": '{"cpf":"123.456.789-00"}'})
            env.get("/admin/executions", params={"parameters": "123.456.789-00"})
        # httpx loga a URL do cliente de teste (não é log da aplicação)
        text = " ".join(r.getMessage() for r in caplog.records if r.name != "httpx")
        assert "123.456.789" not in text and "secreta-xyz" not in text
