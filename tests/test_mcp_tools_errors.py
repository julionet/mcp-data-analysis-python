"""Testes da F14 — contrato "nunca propaga exceção" em mcp_transport/tools.py e main.py
(F14_ERROR_HANDLING_VALIDATION.md §4.4, §5, decisão 6)."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR

import main
from mcp_transport import tools
from repositories.analysis_repo import Analysis
from tests.helpers import make_user
from tests.test_server_setup import _rpc

SECRET = "db-interno.corp:5432 password=Senha123"


def _analysis(name: str = "vendas_por_regiao", is_active: bool = True) -> Analysis:
    return Analysis(
        id=uuid4(), name=name, description="d", data_source_id=uuid4(), parameters={},
        is_active=is_active, updated_at=datetime(2026, 1, 1), cache_frequency="daily",
    )


def _patched(analysis, *, allowed=True, execute=None):
    """Patches comuns de call_tool(): análise resolvida, permissão e execute()."""
    return (
        patch.object(tools.analysis_repo, "get_by_name", AsyncMock(return_value=analysis)),
        patch.object(tools.auth_service, "is_analysis_allowed", AsyncMock(return_value=allowed)),
        patch.object(
            tools.analysis_service, "execute", execute or AsyncMock(return_value={"status": "success", "data": []})
        ),
    )


class TestCallToolNeverRaises:
    @pytest.mark.asyncio
    async def test_config_db_failure_on_lookup_returns_internal_error(self):
        with patch.object(tools.analysis_repo, "get_by_name", AsyncMock(side_effect=RuntimeError(SECRET))):
            result = await tools.call_tool("execute_vendas_por_regiao", {}, make_user())

        assert result == {
            "status": "error",
            "error_code": "INTERNAL_ERROR",
            "retryable": False,
            "mensagem": "Erro interno ao executar a análise.",
            "cached": False,
        }
        assert "Senha123" not in json.dumps(result)

    @pytest.mark.asyncio
    async def test_config_db_failure_on_permission_check_returns_internal_error(self):
        with (
            patch.object(tools.analysis_repo, "get_by_name", AsyncMock(return_value=_analysis())),
            patch.object(tools.auth_service, "is_analysis_allowed", AsyncMock(side_effect=ConnectionError(SECRET))),
            patch.object(tools.analysis_service, "execute", AsyncMock()) as mock_execute,
        ):
            result = await tools.call_tool("execute_vendas_por_regiao", {}, make_user())

        assert result["error_code"] == "INTERNAL_ERROR"
        assert "Senha123" not in json.dumps(result)
        mock_execute.assert_not_awaited()  # falha na checagem de permissão = fail-closed


class TestAccessDeniedLooksLikeNotFound:
    @pytest.mark.asyncio
    async def test_denied_response_is_identical_to_not_found(self):
        user = make_user()
        with patch.object(tools.analysis_repo, "get_by_name", AsyncMock(return_value=None)):
            not_found = await tools.call_tool("execute_custos_financeiros", {}, user)

        analysis = _analysis("custos_financeiros")
        with _patched(analysis, allowed=False)[0], _patched(analysis, allowed=False)[1]:
            denied = await tools.call_tool("execute_custos_financeiros", {}, user)

        assert denied == not_found
        assert denied["error_code"] == "ANALYSIS_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_inactive_analysis_is_not_found(self):
        patches = _patched(_analysis(is_active=False))
        with patches[0], patches[1]:
            result = await tools.call_tool("execute_vendas_por_regiao", {}, make_user())

        assert result["error_code"] == "ANALYSIS_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_denied_is_still_logged(self, caplog):
        user, analysis = make_user(), _analysis("custos_financeiros")
        patches = _patched(analysis, allowed=False)
        with patches[0], patches[1], caplog.at_level("WARNING", logger="mcp_transport.tools"):
            await tools.call_tool("execute_custos_financeiros", {}, user)

        assert f"access_denied user_id={user.id} analysis_id={analysis.id}" in caplog.text


class TestArgumentValidation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_value", ["false", "true", 1, 0, None, [], {}])
    async def test_confirmar_volume_alto_must_be_a_real_boolean(self, bad_value):
        patches = _patched(_analysis())
        with patches[0], patches[1], patches[2] as mock_execute:
            result = await tools.call_tool(
                "execute_vendas_por_regiao", {"confirmar_volume_alto": bad_value}, make_user()
            )

        assert result["error_code"] == "INVALID_PARAMETERS"
        assert result["retryable"] is False
        assert "confirmar_volume_alto" in result["mensagem"]
        mock_execute.assert_not_awaited()  # o Volume Guard nunca é contornado por tipo errado

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [True, False])
    async def test_confirmar_volume_alto_boolean_is_accepted(self, value):
        user, analysis = make_user(), _analysis()
        patches = _patched(analysis)
        with patches[0], patches[1], patches[2] as mock_execute:
            await tools.call_tool("execute_vendas_por_regiao", {"confirmar_volume_alto": value}, user)

        mock_execute.assert_awaited_once_with(analysis.id, {}, value, user_id=user.id)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_arguments", [None, "texto", [1, 2], 42])
    async def test_non_dict_arguments_are_rejected(self, bad_arguments):
        patches = _patched(_analysis())
        with patches[0], patches[1], patches[2] as mock_execute:
            result = await tools.call_tool("execute_vendas_por_regiao", bad_arguments, make_user())

        assert result["error_code"] == "INVALID_PARAMETERS"
        mock_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_validation_never_reveals_a_forbidden_analysis(self):
        patches = _patched(_analysis("custos_financeiros"), allowed=False)
        with patches[0], patches[1], patches[2] as mock_execute:
            result = await tools.call_tool(
                "execute_custos_financeiros", {"confirmar_volume_alto": "false"}, make_user()
            )

        assert result["error_code"] == "ANALYSIS_NOT_FOUND"  # não INVALID_PARAMETERS
        mock_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_callers_dict_is_not_mutated(self):
        arguments = {"data_inicial": "2026-01-01", "confirmar_volume_alto": True}
        patches = _patched(_analysis())
        with patches[0], patches[1], patches[2]:
            await tools.call_tool("execute_vendas_por_regiao", arguments, make_user())

        assert arguments == {"data_inicial": "2026-01-01", "confirmar_volume_alto": True}


class TestListToolsFailure:
    @pytest.mark.asyncio
    async def test_config_db_failure_raises_generic_mcp_error(self):
        with patch.object(
            tools.analysis_service, "get_allowed_analyses", AsyncMock(side_effect=RuntimeError(SECRET))
        ):
            with pytest.raises(McpError) as exc_info:
                await tools.list_tools(make_user())

        assert exc_info.value.error.code == INTERNAL_ERROR
        assert exc_info.value.error.message == "Erro interno ao listar as análises."
        assert "Senha123" not in exc_info.value.error.message


class TestThroughTheRealMcpEndpoint:
    """Com o SDK no meio (mcp 1.30): o que o cliente realmente recebe."""

    def test_tools_list_failure_returns_generic_jsonrpc_error(self, client: TestClient, auth_headers):
        with patch.object(
            tools.analysis_service, "get_allowed_analyses", AsyncMock(side_effect=RuntimeError(SECRET))
        ):
            result = _rpc(client, "tools/list", auth=auth_headers)

        assert result["error"]["code"] == INTERNAL_ERROR
        assert result["error"]["message"] == "Erro interno ao listar as análises."
        assert "Senha123" not in json.dumps(result)

    def test_tools_call_config_db_failure_returns_structured_error(self, client: TestClient, auth_headers):
        with (
            patch.object(tools.analysis_service, "get_allowed_analyses", AsyncMock(return_value=[])),
            patch.object(tools.analysis_repo, "get_by_name", AsyncMock(side_effect=RuntimeError(SECRET))),
        ):
            result = _rpc(
                client, "tools/call", {"name": "execute_vendas_por_regiao", "arguments": {}}, auth=auth_headers
            )

        assert "isError" not in result["result"] or result["result"]["isError"] is False
        payload = json.loads(result["result"]["content"][0]["text"])
        assert payload["error_code"] == "INTERNAL_ERROR"
        assert "Senha123" not in json.dumps(result)


class TestGlobalExceptionHandler:
    def test_is_registered_for_exception(self):
        assert main.app.exception_handlers[Exception] is main.unhandled_exception_handler

    @pytest.mark.asyncio
    async def test_returns_generic_500_without_leaking_the_exception(self):
        response = await main.unhandled_exception_handler(None, RuntimeError(SECRET))

        assert response.status_code == 500
        body = json.loads(response.body)
        assert body == {"error": "internal_error", "message": "Erro interno do servidor."}
        assert "Senha123" not in response.body.decode()
