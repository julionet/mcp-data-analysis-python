"""Testes unitários da F1 — ver F1_FastAPI_MCP_Server_Setup.md §6.1.

F12: o /mcp exige `Authorization: Bearer`; a fixture `client` vive em conftest.py.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from mcp_transport import tools
from repositories.analysis_repo import Analysis
from schemas.auth import AuthFailureReason, InvalidTokenError
from tests.helpers import make_user


class TestServerSetup:
    def test_health_check_returns_ok(self, client: TestClient):
        # F2: TestClient dispara o lifespan real, que conecta ao Config DB
        # configurado em .env — ver F2_POSTGRESQL_ADAPTER.md §6.2 (teste de integração).
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "db": True}

    def test_mcp_route_no_redirect_without_trailing_slash(self, client: TestClient):
        response = client.post("/mcp", json={}, follow_redirects=False)

        assert response.status_code != 307
        assert response.status_code == 401  # F12: sem Authorization, recusado pelo middleware

    def test_cors_middleware_configured(self, client: TestClient):
        response = client.options(
            "/health",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

        assert response.headers.get("access-control-allow-origin") == "*"


_MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

_INIT_PARAMS = {
    "protocolVersion": "2025-03-26",
    "capabilities": {},
    "clientInfo": {"name": "test", "version": "0"},
}


def _rpc(
    client: TestClient,
    method: str,
    params: dict | None = None,
    request_id: int = 1,
    auth: dict | None = None,
) -> dict:
    """POST JSON-RPC em /mcp sem Mcp-Session-Id; aceita resposta JSON ou SSE."""
    body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    response = client.post("/mcp", json=body, headers={**_MCP_HEADERS, **(auth or {})})
    assert response.status_code == 200, response.text
    assert "mcp-session-id" not in response.headers  # stateless: nenhuma sessão é criada
    if response.headers["content-type"].startswith("text/event-stream"):
        data_lines = [ln[len("data:"):].strip() for ln in response.text.splitlines() if ln.startswith("data:")]
        return json.loads(data_lines[-1])
    return response.json()


def _make_analysis(name: str = "vendas_por_regiao") -> Analysis:
    return Analysis(
        id=uuid4(),
        name=name,
        description="Vendas por região",
        data_source_id=uuid4(),
        parameters={},
        is_active=True,
        updated_at=datetime(2026, 1, 1, 12, 0, 0),
        cache_frequency="daily",
    )


class TestStatelessTransport:
    """Regressão da mudança para stateless=True (pré-F12): initialize/tools/list/tools/call
    funcionam como requisições independentes, sem Mcp-Session-Id (agora com Authorization)."""

    def test_initialize_without_session(self, client: TestClient, auth_headers):
        result = _rpc(client, "initialize", _INIT_PARAMS, auth=auth_headers)

        assert result["result"]["serverInfo"]["name"] == "analysis-mcp"

    def test_tools_list_without_session(self, client: TestClient, auth_headers):
        with patch.object(
            tools.analysis_service, "get_allowed_analyses", AsyncMock(return_value=[_make_analysis()])
        ):
            result = _rpc(client, "tools/list", auth=auth_headers)

        assert [t["name"] for t in result["result"]["tools"]] == ["execute_vendas_por_regiao"]

    def test_tools_call_without_session(self, client: TestClient, auth_headers):
        # O SDK chama list_tools() internamente para validar o input de tools/call.
        with (
            patch.object(tools.analysis_service, "get_allowed_analyses", AsyncMock(return_value=[])),
            patch.object(tools.analysis_repo, "get_by_name", AsyncMock(return_value=None)),
        ):
            result = _rpc(
                client, "tools/call", {"name": "execute_inexistente", "arguments": {}}, auth=auth_headers
            )

        payload = json.loads(result["result"]["content"][0]["text"])
        assert payload["status"] == "error"

    def test_requests_are_independent(self, client: TestClient, auth_headers):
        # Duas chamadas seguidas, sem qualquer estado compartilhado entre elas.
        with patch.object(tools.analysis_service, "get_allowed_analyses", AsyncMock(return_value=[])):
            first = _rpc(client, "tools/list", request_id=1, auth=auth_headers)
            second = _rpc(client, "tools/list", request_id=2, auth=auth_headers)

        assert first["result"]["tools"] == [] and second["result"]["tools"] == []


class TestMcpAuthentication:
    """F12 §4.2/§6.3 — o /mcp exige token; o 401 é genérico e sai com headers CORS."""

    @staticmethod
    def _post(client: TestClient, method: str = "tools/list", headers: dict | None = None):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {}}
        return client.post("/mcp", json=body, headers={**_MCP_HEADERS, **(headers or {})})

    def test_no_authorization_returns_401_for_every_method(self, client: TestClient):
        for method in ("initialize", "tools/list", "tools/call"):
            response = self._post(client, method)

            assert response.status_code == 401
            assert response.headers["www-authenticate"] == "Bearer"
            assert response.json() == {
                "error": "unauthorized",
                "message": "Token de acesso inválido ou ausente.",
            }
            assert "mcp-session-id" not in response.headers

    def test_401_carries_cors_headers(self, client: TestClient):
        response = self._post(client, headers={"Origin": "https://example.com"})

        assert response.status_code == 401
        assert response.headers["access-control-allow-origin"] == "*"
        assert "www-authenticate" in response.headers["access-control-expose-headers"].lower()

    def test_cors_preflight_without_authorization_is_not_401(self, client: TestClient):
        response = client.options(
            "/mcp",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "*"

    def test_subpath_mount_also_requires_authorization(self, client: TestClient):
        response = client.post("/mcp/anything", json={}, headers=_MCP_HEADERS)

        assert response.status_code == 401

    def test_invalid_token_returns_same_401(self, client: TestClient, auth_headers):
        response = self._post(client, headers={"Authorization": "Bearer outro-token"})

        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"

    def test_health_and_auth_routes_do_not_need_authorization(self, client: TestClient):
        assert client.get("/health").status_code == 200
        # /auth/token com corpo vazio → 422 de validação (e não o 401 do middleware do /mcp)
        assert client.post("/auth/token", json={}).status_code == 422

    def test_tools_call_denies_without_permission_over_http(self, client: TestClient, auth_headers):
        analysis = _make_analysis("custos")
        with (
            patch.object(tools.analysis_service, "get_allowed_analyses", AsyncMock(return_value=[])),
            patch.object(tools.analysis_repo, "get_by_name", AsyncMock(return_value=analysis)),
            patch.object(tools.auth_service, "is_analysis_allowed", AsyncMock(return_value=False)),
        ):
            result = _rpc(
                client, "tools/call", {"name": "execute_custos", "arguments": {}}, auth=auth_headers
            )

        payload = json.loads(result["result"]["content"][0]["text"])
        assert payload == {"status": "error", "mensagem": "Acesso não autorizado a esta análise."}

    def test_contextvar_isolated_across_users_in_same_client(self, client: TestClient):
        """§4.2 item 4b — regressão contra stateless=False: `initialize` como A e
        `tools/list` como B (sequenciais, mesmo cliente) chegam ao handler como B."""
        user_a, user_b = make_user("A"), make_user("B")
        users = {"token-a": user_a, "token-b": user_b}

        async def fake_authenticate(raw_token: str):
            if raw_token not in users:
                raise InvalidTokenError(AuthFailureReason.TOKEN_NOT_FOUND)
            return users[raw_token]

        seen: list = []

        async def fake_allowed(user_id):
            seen.append(user_id)
            return []

        with (
            patch.object(tools.auth_service, "authenticate", AsyncMock(side_effect=fake_authenticate)),
            patch.object(tools.analysis_service, "get_allowed_analyses", AsyncMock(side_effect=fake_allowed)),
        ):
            _rpc(client, "initialize", _INIT_PARAMS, auth={"Authorization": "Bearer token-a"})
            _rpc(client, "tools/list", auth={"Authorization": "Bearer token-b"})
            _rpc(client, "tools/list", auth={"Authorization": "Bearer token-a"})

        assert seen == [user_b.id, user_a.id]
