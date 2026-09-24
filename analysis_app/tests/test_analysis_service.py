"""Testes unitários da F4 — ver F4_EXECUTION_ENGINE.md §6.1 (TestAnalysisService)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from repositories.analysis_repo import Analysis, AnalysisStep
from repositories.data_source_repo import DataSource
from schemas.exceptions import (
    AnalysisNotFoundError,
    DataSourceConnectionError,
    InvalidAnalysisSchemaError,
    InvalidParametersError,
)
from services.analysis_service import AnalysisService
from services.volume_guard_service import VolumeGuardService

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


def _make_analysis(parameters=None) -> Analysis:
    return Analysis(
        id=uuid4(),
        name="vendas_por_periodo",
        description="Vendas por periodo",
        data_source_id=uuid4(),
        parameters=VENDAS_PARAMETERS if parameters is None else parameters,
        is_active=True,
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


def _service(analysis_repo=None, data_source_repo=None, volume_guard=None) -> AnalysisService:
    return AnalysisService(
        analysis_repo or AsyncMock(),
        data_source_repo or AsyncMock(),
        volume_guard or VolumeGuardService(max_rows=500, max_size_kb=150),
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

        fake_adapter = AsyncMock()
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

        assert result == {"status": "success", "data": expected_dataset}
        fake_adapter.connect.assert_awaited_once()
        fake_adapter.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_analysis_not_found(self):
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = None
        service = _service(analysis_repo)

        with pytest.raises(AnalysisNotFoundError):
            await service.execute(uuid4(), {})

    @pytest.mark.asyncio
    async def test_execute_invalid_params_raises_clear_error(self):
        analysis = _make_analysis()
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        service = _service(analysis_repo)

        with pytest.raises(InvalidParametersError) as exc:
            await service.execute(analysis.id, {"data_final": "2026-01-31"})

        assert "data_inicial" in str(exc.value)

    @pytest.mark.asyncio
    async def test_execute_rejects_malformed_analysis_schema_before_pydantic(self):
        analysis = _make_analysis(parameters={"regiao": {"type": "foo", "required": False}})
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        service = _service(analysis_repo)

        with patch("services.analysis_service.to_pydantic_model") as mock_to_model:
            with pytest.raises(InvalidAnalysisSchemaError):
                await service.execute(analysis.id, {"regiao": "Norte"})

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

        fake_adapter = AsyncMock()
        fake_adapter.execute_query.return_value = 8400  # COUNT(*) já excede o limite

        service = _service(analysis_repo, data_source_repo)

        with (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
            patch("services.analysis_service.decrypt_password", return_value="senha_decifrada"),
        ):
            result = await service.execute(
                analysis.id, {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}
            )

        assert result["status"] == "refinamento_necessario"
        assert fake_adapter.execute_query.await_count == 1  # dataset completo nunca foi buscado
        fake_adapter.disconnect.assert_awaited_once()

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

        fake_adapter = AsyncMock()
        fake_adapter.connect.side_effect = Exception("connection refused: password=Senha123")

        service = _service(analysis_repo, data_source_repo)

        with (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
            patch("services.analysis_service.decrypt_password", return_value="senha_decifrada"),
        ):
            with pytest.raises(DataSourceConnectionError) as exc:
                await service.execute(
                    analysis.id, {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}
                )

        assert "Senha123" not in str(exc.value)
        assert "Traceback" not in str(exc.value)
        fake_adapter.disconnect.assert_awaited_once()

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

        fake_adapter = AsyncMock()
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
        assert ":data_inicial" not in query_sql and ":pago" not in query_sql
        assert list(query_params.keys()) == ["data_inicial", "data_final", "pago"]
