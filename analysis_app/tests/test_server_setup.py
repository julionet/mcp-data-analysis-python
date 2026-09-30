"""Testes unitários da F1 — ver F1_FastAPI_MCP_Server_Setup.md §6.1."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app
from mcp_transport import tools
from repositories.analysis_repo import Analysis


@pytest.fixture(scope="module")
def client():
    # session_manager (mcp_transport) é um singleton de módulo cujo .run()
    # só pode ser chamado uma vez por instância — por isso um único
    # TestClient (um único ciclo de lifespan) é reusado por todos os testes.
    with TestClient(app) as test_client:
        yield test_client


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


def _rpc(client: TestClient, method: str, params: dict | None = None, request_id: int = 1) -> dict:
    """POST JSON-RPC em /mcp sem Mcp-Session-Id; aceita resposta JSON ou SSE."""
    body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    response = client.post("/mcp", json=body, headers=_MCP_HEADERS)
    assert response.status_code == 200, response.text
    assert "mcp-session-id" not in response.headers  # stateless: nenhuma sessão é criada
    if response.headers["content-type"].startswith("text/event-stream"):
        data_lines = [ln[len("data:"):].strip() for ln in response.text.splitlines() if ln.startswith("data:")]
        return json.loads(data_lines[-1])
    return response.json()


class TestStatelessTransport:
    """Regressão da mudança para stateless=True (pré-F12): initialize/tools/list/tools/call
    funcionam como requisições independentes, sem Mcp-Session-Id."""

    def test_initialize_without_session(self, client: TestClient):
        result = _rpc(
            client,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        )

        assert result["result"]["serverInfo"]["name"] == "analysis-mcp"

    def test_tools_list_without_session(self, client: TestClient):
        analysis = Analysis(
            id=uuid4(),
            name="vendas_por_regiao",
            description="Vendas por região",
            data_source_id=uuid4(),
            parameters={},
            is_active=True,
            updated_at=datetime(2026, 1, 1, 12, 0, 0),
            cache_frequency="daily",
        )
        with patch.object(tools.analysis_service, "get_all_analyses", AsyncMock(return_value=[analysis])):
            result = _rpc(client, "tools/list")

        assert [t["name"] for t in result["result"]["tools"]] == ["execute_vendas_por_regiao"]

    def test_tools_call_without_session(self, client: TestClient):
        with patch.object(tools.analysis_repo, "get_by_name", AsyncMock(return_value=None)):
            result = _rpc(client, "tools/call", {"name": "execute_inexistente", "arguments": {}})

        payload = json.loads(result["result"]["content"][0]["text"])
        assert payload["status"] == "error"

    def test_requests_are_independent(self, client: TestClient):
        # Duas chamadas seguidas, sem qualquer estado compartilhado entre elas.
        with patch.object(tools.analysis_service, "get_all_analyses", AsyncMock(return_value=[])):
            first = _rpc(client, "tools/list", request_id=1)
            second = _rpc(client, "tools/list", request_id=2)

        assert first["result"]["tools"] == [] and second["result"]["tools"] == []
