"""Fixtures compartilhadas — F12_AUTENTICACAO_PERFIS.md §6.3.

Não há modo "sem autenticação": a autenticação é contornada só por estas fixtures.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from mcp_transport import tools
from tests.helpers import make_user

TEST_TOKEN = "test-token"


@pytest.fixture(scope="session")
def client():
    # session_manager (mcp_transport) é um singleton de módulo cujo .run()
    # só pode ser chamado uma vez por processo — por isso um único TestClient
    # (um único ciclo de lifespan) é reusado por todos os testes que usam o app real.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_user():
    return make_user()


@pytest.fixture
def auth_headers(auth_user):
    """Patcha AuthService.authenticate: o token `test-token` autentica `auth_user`;
    qualquer outro levanta InvalidTokenError. Devolve os headers da requisição."""
    from schemas.auth import AuthFailureReason, InvalidTokenError

    async def fake_authenticate(raw_token: str):
        if raw_token != TEST_TOKEN:
            raise InvalidTokenError(AuthFailureReason.TOKEN_NOT_FOUND)
        return auth_user

    with patch.object(tools.auth_service, "authenticate", AsyncMock(side_effect=fake_authenticate)):
        yield {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture
def allow_all_analyses():
    with patch.object(tools.auth_service, "is_analysis_allowed", AsyncMock(return_value=True)) as mock:
        yield mock
