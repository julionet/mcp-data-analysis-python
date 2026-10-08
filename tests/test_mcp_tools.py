"""Testes unitários da F5 — ver F5_MCP_TOOLS_INTEGRATION.md §6.1 (TestMcpTools).

F12: list_tools()/call_tool() recebem o `current_user`; ver também test_mcp_tools_auth.py."""

from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from mcp_transport import tools
from repositories.analysis_repo import Analysis
from tests.helpers import make_user

VENDAS_PARAMETERS = {"data_inicial": {"type": "date", "required": True, "description": "..."}}


def _make_analysis(name: str, is_active: bool = True, parameters: dict | None = None) -> Analysis:
    return Analysis(
        id=uuid4(),
        name=name,
        description="Vendas por região",
        data_source_id=uuid4(),
        parameters=VENDAS_PARAMETERS if parameters is None else parameters,
        is_active=is_active,
        updated_at=datetime(2026, 1, 1, 12, 0, 0),
        cache_frequency="daily",
    )


class TestMcpTools:
    @pytest.mark.asyncio
    async def test_list_tools_returns_one_tool_per_active_analysis(self):
        analyses = [_make_analysis("vendas_por_regiao"), _make_analysis("vendas_por_produto")]
        with patch.object(tools.analysis_service, "get_allowed_analyses", AsyncMock(return_value=analyses)):
            result = await tools.list_tools(make_user())

        assert len(result) == 2
        assert {tool.name for tool in result} == {
            "execute_vendas_por_regiao",
            "execute_vendas_por_produto",
        }

    @pytest.mark.asyncio
    async def test_list_tools_skips_analysis_with_invalid_name(self, caplog):
        analyses = [_make_analysis("Vendas Por Regiao")]  # maiúsculas/espaço — fora do padrão
        with patch.object(tools.analysis_service, "get_allowed_analyses", AsyncMock(return_value=analyses)):
            with caplog.at_level("WARNING"):
                result = await tools.list_tools(make_user())

        assert result == []
        assert "Vendas Por Regiao" in caplog.text

    @pytest.mark.asyncio
    async def test_list_tools_injects_confirmar_volume_alto_in_every_schema(self):
        analyses = [_make_analysis("vendas_por_regiao")]
        with patch.object(tools.analysis_service, "get_allowed_analyses", AsyncMock(return_value=analyses)):
            result = await tools.list_tools(make_user())

        schema = result[0].inputSchema
        assert schema["properties"]["confirmar_volume_alto"]["type"] == "boolean"
        assert schema["properties"]["confirmar_volume_alto"]["default"] is False
        assert "data_inicial" in schema["properties"]  # veio de analyses.parameters, intocado

    @pytest.mark.asyncio
    async def test_call_tool_success_returns_status_success(self):
        analysis = _make_analysis("vendas_por_regiao")
        user = make_user()
        with (
            patch.object(tools, "analysis_repo") as mock_repo,
            patch.object(tools.auth_service, "is_analysis_allowed", AsyncMock(return_value=True)),
            patch.object(
                tools.analysis_service,
                "execute",
                AsyncMock(return_value={"status": "success", "data": []}),
            ) as mock_execute,
        ):
            mock_repo.get_by_name = AsyncMock(return_value=analysis)
            result = await tools.call_tool(
                "execute_vendas_por_regiao", {"data_inicial": "2026-01-01"}, user
            )

        assert result == {"status": "success", "data": []}
        mock_execute.assert_awaited_once_with(
            analysis.id, {"data_inicial": "2026-01-01"}, False, user_id=user.id
        )

    @pytest.mark.asyncio
    async def test_call_tool_passes_confirmar_volume_alto_and_strips_it_from_arguments(self):
        analysis = _make_analysis("vendas_por_regiao")
        user = make_user()
        with (
            patch.object(tools, "analysis_repo") as mock_repo,
            patch.object(tools.auth_service, "is_analysis_allowed", AsyncMock(return_value=True)),
            patch.object(
                tools.analysis_service,
                "execute",
                AsyncMock(return_value={"status": "success", "data": []}),
            ) as mock_execute,
        ):
            mock_repo.get_by_name = AsyncMock(return_value=analysis)
            await tools.call_tool(
                "execute_vendas_por_regiao",
                {"data_inicial": "2026-01-01", "confirmar_volume_alto": True},
                user,
            )

        mock_execute.assert_awaited_once_with(
            analysis.id, {"data_inicial": "2026-01-01"}, True, user_id=user.id
        )

    @pytest.mark.asyncio
    async def test_call_tool_analysis_not_found_returns_status_error(self):
        with (
            patch.object(tools, "analysis_repo") as mock_repo,
            patch.object(tools.auth_service, "is_analysis_allowed", AsyncMock()) as mock_allowed,
        ):
            mock_repo.get_by_name = AsyncMock(return_value=None)
            result = await tools.call_tool("execute_analise_que_nao_existe", {}, make_user())

        assert result["status"] == "error"
        mock_allowed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_call_tool_inactive_analysis_returns_status_error(self):
        analysis = _make_analysis("vendas_por_regiao", is_active=False)
        with (
            patch.object(tools, "analysis_repo") as mock_repo,
            patch.object(tools.auth_service, "is_analysis_allowed", AsyncMock()) as mock_allowed,
        ):
            mock_repo.get_by_name = AsyncMock(return_value=analysis)
            result = await tools.call_tool("execute_vendas_por_regiao", {}, make_user())

        assert result["status"] == "error"
        mock_allowed.assert_not_awaited()  # a análise é resolvida antes da permissão

    @pytest.mark.asyncio
    async def test_call_tool_never_raises_on_internal_exception(self):
        # analysis_service.execute() já garante nunca propagar (F5, ajuste
        # retroativo) — call_tool() apenas repassa o dict, sem try/except
        # próprio (§4.2 passo 9); este teste confirma que nada nesse repasse
        # reintroduz uma exceção para o transporte MCP.
        analysis = _make_analysis("vendas_por_regiao")
        user = make_user()
        with (
            patch.object(tools, "analysis_repo") as mock_repo,
            patch.object(tools.auth_service, "is_analysis_allowed", AsyncMock(return_value=True)),
            patch.object(
                tools.analysis_service,
                "execute",
                AsyncMock(return_value={"status": "error", "mensagem": "Erro interno ao executar a análise."}),
            ),
        ):
            mock_repo.get_by_name = AsyncMock(return_value=analysis)
            result = await tools.call_tool("execute_vendas_por_regiao", {}, user)

        assert result == {"status": "error", "mensagem": "Erro interno ao executar a análise."}


class TestCacheBackendSelection:
    """F17 M3 — CACHE_BACKEND=none instala o NullBackend (kill-switch global) e avisa no log."""

    @staticmethod
    def _load_fresh_copy(cache_backend: str):
        """Executa uma CÓPIA de mcp_transport/tools.py com outro `settings.cache_backend`,
        sem tocar nos singletons do módulo real (que o resto da suíte usa)."""
        import importlib.util

        from config import settings
        from mcp_transport import tools as real

        spec = importlib.util.spec_from_file_location("tools_cache_backend_copy", real.__file__)
        module = importlib.util.module_from_spec(spec)
        with patch.object(settings, "cache_backend", cache_backend):
            spec.loader.exec_module(module)
        return module

    def test_none_installs_null_backend_and_logs_warning(self, caplog):
        import logging

        from services.cache_backend import NullBackend

        with caplog.at_level(logging.WARNING):
            module = self._load_fresh_copy("none")

        assert isinstance(module._cache_backend, NullBackend)
        assert any("CACHE_BACKEND=none" in r.getMessage() for r in caplog.records)

    def test_memory_installs_in_memory_backend(self):
        from services.cache_backend import InMemoryBackend

        assert isinstance(self._load_fresh_copy("memory")._cache_backend, InMemoryBackend)
