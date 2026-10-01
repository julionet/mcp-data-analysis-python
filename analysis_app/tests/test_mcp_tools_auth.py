"""mcp_transport/tools.py com AuthenticatedUser — F12_AUTENTICACAO_PERFIS.md §6.1."""

from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from mcp_transport import tools
from repositories.analysis_repo import Analysis
from tests.helpers import make_user


def _analysis(name: str = "vendas_por_regiao") -> Analysis:
    return Analysis(
        id=uuid4(), name=name, description="d", data_source_id=uuid4(), parameters={},
        is_active=True, updated_at=datetime(2026, 1, 1), cache_frequency="daily",
    )


class TestMcpToolsAuth:
    @pytest.mark.asyncio
    async def test_call_tool_denies_before_cache_lookup(self):
        analysis, user = _analysis("custos_financeiros"), make_user()
        with (
            patch.object(tools.analysis_repo, "get_by_name", AsyncMock(return_value=analysis)),
            patch.object(tools.auth_service, "is_analysis_allowed", AsyncMock(return_value=False)),
            patch.object(tools.analysis_service, "execute", AsyncMock()) as mock_execute,
            patch.object(tools._cache_service, "get_or_execute", AsyncMock()) as mock_cache,
        ):
            result = await tools.call_tool("execute_custos_financeiros", {}, user)

        assert result == {"status": "error", "mensagem": "Acesso não autorizado a esta análise."}
        mock_execute.assert_not_awaited()
        mock_cache.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_tools_filters_by_user_permission(self):
        user = make_user()
        allowed = [_analysis("vendas_por_regiao")]
        with patch.object(
            tools.analysis_service, "get_allowed_analyses", AsyncMock(return_value=allowed)
        ) as mock_allowed:
            result = await tools.list_tools(user)

        assert [t.name for t in result] == ["execute_vendas_por_regiao"]
        mock_allowed.assert_awaited_once_with(user.id)

    @pytest.mark.asyncio
    async def test_list_tools_empty_when_no_profile(self):
        with patch.object(tools.analysis_service, "get_allowed_analyses", AsyncMock(return_value=[])):
            assert await tools.list_tools(make_user()) == []

    @pytest.mark.asyncio
    async def test_call_tool_revalidates_permission(self):
        analysis, user = _analysis(), make_user()
        with (
            patch.object(tools.analysis_repo, "get_by_name", AsyncMock(return_value=analysis)),
            patch.object(tools.auth_service, "is_analysis_allowed", AsyncMock(return_value=True)) as mock_allowed,
            patch.object(tools.analysis_service, "execute", AsyncMock(return_value={"status": "success"})),
        ):
            await tools.call_tool("execute_vendas_por_regiao", {}, user)

        mock_allowed.assert_awaited_once_with(user.id, analysis.id)

    @pytest.mark.asyncio
    async def test_call_tool_denies_when_permission_revoked_after_list(self):
        analysis, user = _analysis(), make_user()
        permitted = AsyncMock(return_value=True)
        with (
            patch.object(tools.analysis_repo, "get_by_name", AsyncMock(return_value=analysis)),
            patch.object(tools.analysis_service, "get_allowed_analyses", AsyncMock(return_value=[analysis])),
            patch.object(tools.auth_service, "is_analysis_allowed", permitted),
            patch.object(
                tools.analysis_service, "execute", AsyncMock(return_value={"status": "success"})
            ) as mock_execute,
        ):
            listed = await tools.list_tools(user)
            permitted.return_value = False  # vínculo removido entre as duas chamadas
            result = await tools.call_tool("execute_vendas_por_regiao", {}, user)

        assert [t.name for t in listed] == ["execute_vendas_por_regiao"]
        assert result["status"] == "error"
        mock_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_call_tool_logs_access_denied(self, caplog):
        analysis, user = _analysis("custos_financeiros"), make_user()
        with (
            patch.object(tools.analysis_repo, "get_by_name", AsyncMock(return_value=analysis)),
            patch.object(tools.auth_service, "is_analysis_allowed", AsyncMock(return_value=False)),
            caplog.at_level("WARNING", logger="mcp_transport.tools"),
        ):
            await tools.call_tool("execute_custos_financeiros", {"x": 1}, user)

        message = next(r.getMessage() for r in caplog.records if r.levelname == "WARNING")
        assert message == (
            f"access_denied user_id={user.id} analysis_id={analysis.id} analysis_name=custos_financeiros"
        )

    @pytest.mark.asyncio
    async def test_call_tool_logs_user_id_in_execution_history(self):
        """Do call_tool() até ExecutionRepository.create(): o user_id chega gravado."""
        analysis, user = _analysis(), make_user()
        with (
            patch.object(tools.analysis_repo, "get_by_name", AsyncMock(return_value=analysis)),
            patch.object(tools.auth_service, "is_analysis_allowed", AsyncMock(return_value=True)),
            patch.object(tools.analysis_repo, "get_by_id", AsyncMock(return_value=analysis)),
            patch.object(tools._execution_repo, "create", AsyncMock()) as mock_create,
        ):
            # parâmetros inválidos para sair cedo, mas ainda assim passando pelo audit
            result = await tools.call_tool("execute_vendas_por_regiao", {"inexistente": 1}, user)

        assert "status" in result
        assert mock_create.await_args.kwargs["user_id"] == user.id
