"""Testes unitários da F4 — ver F4_EXECUTION_ENGINE.md §6.1 (TestAnalysisService).

F5 (ajuste retroativo, F5_MCP_TOOLS_INTEGRATION.md §6.1 TestAnalysisServiceExecuteContract):
execute() passou a nunca propagar exceção — os testes abaixo que antes
verificavam `pytest.raises(...)` agora verificam o dict {"status": "error", ...}.

F4 (ajuste retroativo, 2026-09-26): o adapter deixou de ser desconectado a
cada execute() — fica cacheado em AnalysisService._adapters e só é fechado
por aclose() (shutdown). Os testes abaixo não verificam mais
`disconnect.assert_awaited_once()` por chamada; ver TestAnalysisServiceAdapterCache.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from repositories.analysis_repo import Analysis, AnalysisStep
from repositories.data_source_repo import DataSource
from services.analysis_service import AnalysisService
from services.cache_backend import InMemoryBackend
from services.cache_service import CacheService
from services.volume_guard_service import VolumeGuardService
from tests.helpers import make_fake_adapter

VENDAS_PARAMETERS = {
    "data_inicial": {"type": "date", "required": True, "description": "..."},
    "data_final": {"type": "date", "required": True, "description": "..."},
    "pago": {"type": "boolean", "required": False, "description": "..."},
}

VENDAS_SQL = (
    "SELECT data, valor, pago FROM vendas "
    "WHERE data BETWEEN :data_inicial AND :data_final "
    "AND (:pago IS NULL OR pago = :pago) ORDER BY data"
)


def _make_analysis(parameters=None, updated_at=None, cache_frequency="daily") -> Analysis:
    return Analysis(
        id=uuid4(),
        name="vendas_por_periodo",
        description="Vendas por periodo",
        data_source_id=uuid4(),
        parameters=VENDAS_PARAMETERS if parameters is None else parameters,
        is_active=True,
        updated_at=updated_at or datetime(2026, 1, 1, 12, 0, 0),
        cache_frequency=cache_frequency,
    )


def _make_data_source(analysis: Analysis) -> DataSource:
    return DataSource(
        id=analysis.data_source_id,
        name="vendas_db_local",
        type="postgresql",
        connection_config={
            "host": "localhost",
            "port": 5432,
            "database": "data_db",
            "user": "chronus",
            "password": "cifrada",
            "sslmode": "prefer",
        },
        is_active=True,
    )


def _make_step(analysis: Analysis) -> AnalysisStep:
    return AnalysisStep(
        id=uuid4(),
        analysis_id=analysis.id,
        step_order=1,
        step_type="query",
        definition={"sql": VENDAS_SQL, "params": ["data_inicial", "data_final", "pago"]},
    )


def _service(
    analysis_repo=None, data_source_repo=None, volume_guard=None, cache_service=None, audit_service=None
) -> AnalysisService:
    return AnalysisService(
        analysis_repo or AsyncMock(),
        data_source_repo or AsyncMock(),
        volume_guard or VolumeGuardService(max_rows=500, max_size_kb=150),
        cache_service
        or CacheService(InMemoryBackend(max_entries=1000, max_size_mb=100), max_rows=500, max_size_kb=150),
        audit_service or AsyncMock(),
    )


class TestAnalysisService:
    @pytest.mark.asyncio
    async def test_execute_success_returns_raw_dataset(self):
        analysis = _make_analysis()
        data_source = _make_data_source(analysis)
        step = _make_step(analysis)

        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [step]

        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = data_source

        fake_adapter = make_fake_adapter()
        expected_dataset = [{"data": "2026-01-05", "valor": 100.0, "pago": True}]
        fake_adapter.execute_query.side_effect = [1, expected_dataset]

        service = _service(analysis_repo, data_source_repo)

        with (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
            patch("services.analysis_service.decrypt_password", return_value="senha_decifrada"),
        ):
            result = await service.execute(
                analysis.id, {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}
            )

        assert result == {"status": "success", "data": expected_dataset, "cached": False}
        fake_adapter.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_analysis_not_found(self):
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = None
        service = _service(analysis_repo)

        result = await service.execute(uuid4(), {})

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_execute_invalid_params_returns_error_with_clear_message(self):
        analysis = _make_analysis()
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        service = _service(analysis_repo)

        result = await service.execute(analysis.id, {"data_final": "2026-01-31"})

        assert result["status"] == "error"
        assert "data_inicial" in result["mensagem"]

    @pytest.mark.asyncio
    async def test_execute_rejects_malformed_analysis_schema_before_pydantic(self):
        analysis = _make_analysis(parameters={"regiao": {"type": "foo", "required": False}})
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        service = _service(analysis_repo)

        with patch("services.analysis_service.to_pydantic_model") as mock_to_model:
            result = await service.execute(analysis.id, {"regiao": "Norte"})

        assert result["status"] == "error"
        mock_to_model.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_stops_before_full_query_on_volume_exceeded(self):
        analysis = _make_analysis()
        data_source = _make_data_source(analysis)
        step = _make_step(analysis)

        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [step]

        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = data_source

        fake_adapter = make_fake_adapter()
        fake_adapter.execute_query.return_value = 8400  # COUNT(*) já excede o limite

        service = _service(analysis_repo, data_source_repo)

        with (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
            patch("services.analysis_service.decrypt_password", return_value="senha_decifrada"),
        ):
            result = await service.execute(
                analysis.id, {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}
            )

        assert result["status"] == "volume_exceeded"
        assert fake_adapter.execute_query.await_count == 1  # dataset completo nunca foi buscado

    @pytest.mark.asyncio
    async def test_execute_wraps_connection_error_without_stacktrace(self):
        analysis = _make_analysis()
        data_source = _make_data_source(analysis)
        step = _make_step(analysis)

        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [step]

        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = data_source

        fake_adapter = make_fake_adapter()
        fake_adapter.connect.side_effect = Exception("connection refused: password=Senha123")

        service = _service(analysis_repo, data_source_repo)

        with (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
            patch("services.analysis_service.decrypt_password", return_value="senha_decifrada"),
        ):
            result = await service.execute(
                analysis.id, {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}
            )

        assert result["status"] == "error"
        assert "Senha123" not in result["mensagem"]
        assert "Traceback" not in result["mensagem"]

    @pytest.mark.asyncio
    async def test_execute_confirmar_volume_alto_bypasses_limit_and_adds_aviso(self):
        analysis = _make_analysis()
        data_source = _make_data_source(analysis)
        step = _make_step(analysis)

        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [step]

        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = data_source

        fake_adapter = make_fake_adapter()
        expected_dataset = [{"data": "2026-01-05", "valor": 100.0, "pago": True}] * 5000
        fake_adapter.execute_query.return_value = expected_dataset  # sem COUNT(*) — bypass

        service = _service(analysis_repo, data_source_repo)

        with (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
            patch("services.analysis_service.decrypt_password", return_value="senha_decifrada"),
        ):
            result = await service.execute(
                analysis.id,
                {"data_inicial": "2026-01-01", "data_final": "2026-01-31"},
                confirmar_volume_alto=True,
            )

        assert result["status"] == "success"
        assert result["data"] == expected_dataset
        assert result["aviso"] == "resultado grande, enviado por confirmação explícita"
        assert fake_adapter.execute_query.await_count == 1  # nenhum COUNT(*) foi executado

    @pytest.mark.asyncio
    async def test_execute_internal_error_returns_error_dict_never_raises(self):
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.side_effect = RuntimeError("bug inesperado")
        service = _service(analysis_repo)

        result = await service.execute(uuid4(), {})

        assert result == {
            "status": "error",
            "error_code": "INTERNAL_ERROR",  # F14
            "retryable": False,
            "mensagem": "Erro interno ao executar a análise.",
            "cached": False,
        }

    @pytest.mark.asyncio
    async def test_execute_translates_named_params_to_positional(self):
        analysis = _make_analysis()
        data_source = _make_data_source(analysis)
        step = _make_step(analysis)

        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [step]

        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = data_source

        fake_adapter = make_fake_adapter()
        fake_adapter.execute_query.side_effect = [1, []]

        service = _service(analysis_repo, data_source_repo)

        with (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
            patch("services.analysis_service.decrypt_password", return_value="senha_decifrada"),
        ):
            await service.execute(
                analysis.id, {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}
            )

        count_call, query_call = fake_adapter.execute_query.await_args_list
        count_sql = count_call.args[0]
        query_sql, query_params = query_call.args[0], query_call.args[1]

        assert "$1" in count_sql and "$2" in count_sql and "$3" in count_sql
        assert count_sql.endswith(") sub") and " AS sub" not in count_sql  # F9: Oracle rejeita AS
        assert ":data_inicial" not in query_sql and ":pago" not in query_sql
        assert list(query_params.keys()) == ["data_inicial", "data_final", "pago"]


class TestAnalysisServiceAdapterCache:
    """F4 (ajuste retroativo, 2026-09-26) — pool de conexão reutilizado por
    data_source_id em vez de aberto/fechado a cada execute()."""

    @pytest.mark.asyncio
    async def test_execute_reuses_adapter_across_calls_for_same_data_source(self):
        analysis = _make_analysis()
        data_source = _make_data_source(analysis)
        step = _make_step(analysis)

        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [step]

        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = data_source

        fake_adapter = make_fake_adapter()
        fake_adapter.execute_query.side_effect = [1, [], 1, []]  # 2 execuções, COUNT + SELECT cada

        service = _service(analysis_repo, data_source_repo)

        with (
            patch(
                "services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter
            ) as mock_create_adapter,
            patch("services.analysis_service.decrypt_password", return_value="senha_decifrada"),
        ):
            params = {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}
            result_1 = await service.execute(analysis.id, params)
            result_2 = await service.execute(analysis.id, params)

        assert result_1["status"] == "success"
        assert result_2["status"] == "success"
        mock_create_adapter.assert_called_once()  # adapter criado só na 1ª chamada
        fake_adapter.connect.assert_awaited_once()  # conectado só na 1ª chamada
        fake_adapter.disconnect.assert_not_awaited()  # nunca desconectado entre chamadas

    @pytest.mark.asyncio
    async def test_aclose_disconnects_all_cached_adapters(self):
        analysis = _make_analysis()
        data_source = _make_data_source(analysis)
        step = _make_step(analysis)

        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [step]

        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = data_source

        fake_adapter = make_fake_adapter()
        fake_adapter.execute_query.side_effect = [1, []]

        service = _service(analysis_repo, data_source_repo)

        with (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
            patch("services.analysis_service.decrypt_password", return_value="senha_decifrada"),
        ):
            await service.execute(
                analysis.id, {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}
            )

        await service.aclose()

        fake_adapter.disconnect.assert_awaited_once()
        assert service._adapters == {}


class TestAnalysisServiceStepValidation:
    """Steps ausentes e SQL que não é SELECT viram erro de configuração
    claro, sem abrir conexão com o data source."""

    async def _execute_with_steps(self, steps):
        analysis = _make_analysis()
        data_source = _make_data_source(analysis)

        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = steps(analysis)

        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = data_source

        audit_service = AsyncMock()
        service = _service(analysis_repo, data_source_repo, audit_service=audit_service)

        with patch("services.analysis_service.AdapterFactory.create_adapter") as mock_create_adapter:
            result = await service.execute(analysis.id, {"data_inicial": "2026-01-01", "data_final": "2026-01-31"})

        mock_create_adapter.assert_not_called()
        return result, audit_service

    @pytest.mark.asyncio
    async def test_execute_without_steps_returns_clear_error(self):
        result, audit_service = await self._execute_with_steps(lambda analysis: [])

        assert result["status"] == "error"
        assert "nenhum step" in result["mensagem"]
        assert result["mensagem"] != "Erro interno ao executar a análise."
        assert audit_service.log_execution.await_args.kwargs["status"] == "error"

    @pytest.mark.asyncio
    async def test_execute_rejects_non_select_sql(self):
        def steps(analysis):
            step = _make_step(analysis)
            step.definition = {"sql": "DELETE FROM vendas WHERE data < :data_inicial", "params": ["data_inicial"]}
            return [step]

        result, audit_service = await self._execute_with_steps(steps)

        assert result["status"] == "error"
        assert "SELECT" in result["mensagem"]
        assert result["cached"] is False
        assert audit_service.log_execution.await_args.kwargs["status"] == "error"


class TestAnalysisServiceSQLServer:
    """F11 — AnalysisService com data_source sqlserver (adapter real, driver mockado)."""

    @pytest.mark.asyncio
    async def test_execute_runs_volume_guard_and_query_with_positional_values(self):
        from unittest.mock import MagicMock

        from adapters.sqlserver import SQLServerAdapter

        analysis = _make_analysis()
        data_source = _make_data_source(analysis)
        data_source.type = "sqlserver"
        step = _make_step(analysis)
        step.definition["sql"] = VENDAS_SQL.replace(" ORDER BY data", "")  # subconjunto comum (F11 §8.4)

        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [step]
        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = data_source

        cursor = MagicMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(1,))
        cursor.fetchall = AsyncMock(return_value=[("2026-01-05", 100.0, True)])
        cursor.description = [("data",), ("valor",), ("pago",)]
        conn = MagicMock()
        conn.cursor.return_value.__aenter__.return_value = cursor
        pool = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = conn

        async def fake_connect(self):
            self._pool = pool

        service = _service(analysis_repo, data_source_repo)

        with (
            patch.object(SQLServerAdapter, "connect", fake_connect),
            patch("services.analysis_service.decrypt_password", return_value="senha_decifrada"),
        ):
            result = await service.execute(
                analysis.id, {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}
            )

        assert result == {
            "status": "success",
            "data": [{"data": "2026-01-05", "valor": 100.0, "pago": True}],
            "cached": False,
        }
        count_call, query_call = cursor.execute.await_args_list
        assert count_call.args[0].startswith("SELECT COUNT(*) FROM (SELECT data, valor, pago FROM vendas")
        assert "?" in count_call.args[0] and "@" not in count_call.args[0]
        # data_inicial, data_final, pago, pago (parâmetro repetido → valor repetido)
        assert len(query_call.args) == 1 + 4
        assert query_call.args[-2:] == (None, None)


class TestAnalysisServiceAllowedAnalyses:
    """F12 — get_allowed_analyses() delega ao repositório com o user_id."""

    @pytest.mark.asyncio
    async def test_get_allowed_analyses_delegates_to_repo(self):
        analysis_repo = AsyncMock()
        analyses = [_make_analysis()]
        analysis_repo.get_allowed_for_user.return_value = analyses
        user_id = uuid4()

        result = await _service(analysis_repo).get_allowed_analyses(user_id)

        assert result == analyses
        analysis_repo.get_allowed_for_user.assert_awaited_once_with(user_id)
