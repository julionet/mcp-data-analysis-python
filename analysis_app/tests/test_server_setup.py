"""Testes unitários da F1 — ver F1_FastAPI_MCP_Server_Setup.md §6.1."""

import pytest
from fastapi.testclient import TestClient

from main import app


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
