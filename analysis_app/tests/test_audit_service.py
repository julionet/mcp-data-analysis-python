"""Testes para AuditService — logging de execução em execution_history (F8)."""

from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from repositories.analysis_repo import Analysis, AnalysisStep
from repositories.data_source_repo import DataSource
from services.analysis_service import AnalysisService
from services.audit_service import AuditService
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


def _make_analysis(
    parameters=None, updated_at=None, cache_frequency="daily"
) -> Analysis:
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


class TestAuditService:
    @pytest.mark.asyncio
    async def test_log_execution_success_computes_rows_and_size(self):
        execution_repo = AsyncMock()
        audit_service = AuditService(execution_repo)

        analysis_id = uuid4()
        params = {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}
        result = {"status": "success", "data": [{"valor": 100}, {"valor": 200}]}

        await audit_service.log_execution(
            analysis_id=analysis_id,
            parameters=params,
            status="success",
            execution_time_ms=150,
            cached=False,
            result=result,
        )

        execution_repo.create.assert_awaited_once()
        call_args = execution_repo.create.call_args
        assert call_args[1]["status"] == "success"
        assert call_args[1]["rows_affected"] == 2
        assert call_args[1]["result_size_bytes"] is not None
        assert call_args[1]["result_size_bytes"] > 0

    @pytest.mark.asyncio
    async def test_log_execution_volume_exceeded_uses_estimate(self):
        execution_repo = AsyncMock()
        audit_service = AuditService(execution_repo)

        analysis_id = uuid4()
        params = {"regiao": "sul"}
        result = {
            "status": "volume_exceeded",
            "estimativa": {"linhas": 1000000, "tamanho_estimado_kb": 50000},
            "limite": {"linhas": 500000, "tamanho_kb": 150},
        }

        await audit_service.log_execution(
            analysis_id=analysis_id,
            parameters=params,
            status="volume_exceeded",
            execution_time_ms=50,
            cached=False,
            result=result,
        )

        execution_repo.create.assert_awaited_once()
        call_args = execution_repo.create.call_args
        assert call_args[1]["status"] == "volume_exceeded"
        assert call_args[1]["rows_affected"] == 1000000
        assert call_args[1]["result_size_bytes"] == 50000 * 1024

    @pytest.mark.asyncio
    async def test_log_execution_error_sets_error_message_only(self):
        execution_repo = AsyncMock()
        audit_service = AuditService(execution_repo)

        analysis_id = uuid4()
        params = {}
        error_msg = "Parâmetros inválidos — data_inicial: field required"

        await audit_service.log_execution(
            analysis_id=analysis_id,
            parameters=params,
            status="error",
            execution_time_ms=0,
            cached=False,
            error_message=error_msg,
        )

        execution_repo.create.assert_awaited_once()
        call_args = execution_repo.create.call_args
        assert call_args[1]["status"] == "error"
        assert call_args[1]["error_message"] == error_msg
        assert call_args[1]["rows_affected"] is None
        assert call_args[1]["result_size_bytes"] is None

    @pytest.mark.asyncio
    async def test_log_execution_failure_does_not_raise(self):
        execution_repo = AsyncMock()
        execution_repo.create.side_effect = Exception("Database connection failed")
        audit_service = AuditService(execution_repo)

        analysis_id = uuid4()

        # Não deve lançar exceção mesmo com falha no repositório
        await audit_service.log_execution(
            analysis_id=analysis_id,
            parameters={},
            status="success",
            execution_time_ms=100,
            cached=False,
            result={"status": "success", "data": []},
        )

        # O repositório foi chamado mas não propagou a exceção
        execution_repo.create.assert_awaited_once()


class TestAnalysisServiceAudit:
    @pytest.mark.asyncio
    async def test_analysis_not_found_does_not_call_audit(self):
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = None
        audit_service = AsyncMock()

        service = AnalysisService(
            analysis_repo,
            AsyncMock(),
            VolumeGuardService(500, 150),
            CacheService(InMemoryBackend(1000, 100), 500, 150),
            audit_service,
        )

        result = await service.execute(uuid4(), {})

        assert result["status"] == "error"
        # AnalysisNotFoundError não deve chamar audit_service.log_execution
        audit_service.log_execution.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_success_logs_execution_with_correct_params(self):
        analysis = _make_analysis()
        data_source = _make_data_source(analysis)
        step = _make_step(analysis)

        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [step]

        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = data_source

        fake_adapter = make_fake_adapter()
        expected_dataset = [{"data": "2026-01-05", "valor": 100}]

        async def mock_execute_query(sql, params, scalar=False):
            if scalar:
                return 1  # count result
            return expected_dataset

        fake_adapter.execute_query = AsyncMock(side_effect=mock_execute_query)

        audit_service = AsyncMock()

        service = AnalysisService(
            analysis_repo,
            data_source_repo,
            VolumeGuardService(500, 150),
            CacheService(InMemoryBackend(1000, 100), 500, 150),
            audit_service,
        )

        with (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
            patch("services.analysis_service.decrypt_password", return_value="senha"),
        ):
            params = {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}
            result = await service.execute(analysis.id, params)

        assert result["status"] == "success"
        audit_service.log_execution.assert_awaited_once()
        call_args = audit_service.log_execution.call_args
        assert call_args[1]["analysis_id"] == analysis.id
        assert call_args[1]["status"] == "success"
        assert call_args[1]["cached"] is False
        assert call_args[1]["execution_time_ms"] >= 0

    @pytest.mark.asyncio
    async def test_error_logs_execution_with_error_message(self):
        analysis = _make_analysis()
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        audit_service = AsyncMock()

        service = AnalysisService(
            analysis_repo,
            AsyncMock(),
            VolumeGuardService(500, 150),
            CacheService(InMemoryBackend(1000, 100), 500, 150),
            audit_service,
        )

        # Parâmetros inválidos (falta data_inicial)
        result = await service.execute(analysis.id, {"data_final": "2026-01-31"})

        assert result["status"] == "error"
        audit_service.log_execution.assert_awaited_once()
        call_args = audit_service.log_execution.call_args
        assert call_args[1]["status"] == "error"
        assert "data_inicial" in call_args[1]["error_message"]
        assert call_args[1]["execution_time_ms"] == 0
        assert call_args[1]["cached"] is False

    @pytest.mark.asyncio
    async def test_cache_hit_logs_execution_time_zero(self):
        analysis = _make_analysis(cache_frequency="daily")
        data_source = _make_data_source(analysis)
        step = _make_step(analysis)

        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [step]

        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = data_source

        fake_adapter = make_fake_adapter()
        expected_dataset = [{"valor": 100}]

        async def mock_execute_query(sql, params, scalar=False):
            if scalar:
                return 1  # count result
            return expected_dataset

        fake_adapter.execute_query = AsyncMock(side_effect=mock_execute_query)

        cache_backend = InMemoryBackend(1000, 100)
        cache_service = CacheService(cache_backend, 500, 150)
        audit_service = AsyncMock()

        service = AnalysisService(
            analysis_repo,
            data_source_repo,
            VolumeGuardService(500, 150),
            cache_service,
            audit_service,
        )

        with (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
            patch("services.analysis_service.decrypt_password", return_value="senha"),
        ):
            params = {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}

            # Primeira execução (MISS)
            result1 = await service.execute(analysis.id, params)
            assert result1["status"] == "success"
            assert result1["cached"] is False

            # Segunda execução (HIT)
            result2 = await service.execute(analysis.id, params)
            assert result2["status"] == "success"
            assert result2["cached"] is True

        # Log foi chamado 2 vezes (uma por execução)
        assert audit_service.log_execution.await_count == 2
        # A segunda chamada (HIT) teve execution_time_ms = 0
        call_args_hit = audit_service.log_execution.call_args_list[1]
        assert call_args_hit[1]["execution_time_ms"] == 0
        assert call_args_hit[1]["cached"] is True


class TestAuditServiceUserId:
    """F12 — user_id repassado ao ExecutionRepository."""

    @pytest.mark.asyncio
    async def test_user_id_is_passed_to_repo(self):
        execution_repo = AsyncMock()
        user_id = uuid4()

        await AuditService(execution_repo).log_execution(
            analysis_id=uuid4(),
            parameters={},
            status="success",
            execution_time_ms=1,
            cached=False,
            result={"status": "success", "data": []},
            user_id=user_id,
        )

        assert execution_repo.create.call_args[1]["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_user_id_omitted_defaults_to_none(self):
        execution_repo = AsyncMock()

        await AuditService(execution_repo).log_execution(
            analysis_id=uuid4(),
            parameters={},
            status="success",
            execution_time_ms=1,
            cached=False,
            result={"status": "success", "data": []},
        )

        assert execution_repo.create.call_args[1]["user_id"] is None


class TestAnalysisServiceAuditUserId:
    """F12 — AnalysisService.execute(..., user_id=) chega ao log_execution em todos os caminhos."""

    @staticmethod
    def _build(count_or_dataset, cache_frequency="daily"):
        analysis = _make_analysis(cache_frequency=cache_frequency)
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [_make_step(analysis)]
        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = _make_data_source(analysis)
        fake_adapter = make_fake_adapter()
        fake_adapter.execute_query.side_effect = count_or_dataset
        audit_service = AsyncMock()
        service = AnalysisService(
            analysis_repo,
            data_source_repo,
            VolumeGuardService(500, 150),
            CacheService(InMemoryBackend(1000, 100), 500, 150),
            audit_service,
        )
        return analysis, service, fake_adapter, audit_service

    _PARAMS = {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}

    def _patches(self, fake_adapter):
        return (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
            patch("services.analysis_service.decrypt_password", return_value="senha"),
        )

    @pytest.mark.asyncio
    async def test_success_logs_user_id(self):
        analysis, service, adapter, audit = self._build([1, [{"valor": 1}]])
        user_id = uuid4()
        p1, p2 = self._patches(adapter)
        with p1, p2:
            result = await service.execute(analysis.id, self._PARAMS, user_id=user_id)

        assert result["status"] == "success"
        assert audit.log_execution.call_args[1]["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_error_logs_user_id(self):
        analysis, service, _, audit = self._build([])
        user_id = uuid4()

        result = await service.execute(analysis.id, {"data_final": "2026-01-31"}, user_id=user_id)

        assert result["status"] == "error"
        assert audit.log_execution.call_args[1]["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_unexpected_error_logs_user_id(self):
        analysis, service, adapter, audit = self._build([])
        user_id = uuid4()
        with patch("services.analysis_service.to_pydantic_model", side_effect=RuntimeError("boom")):
            result = await service.execute(analysis.id, self._PARAMS, user_id=user_id)

        assert result["status"] == "error"
        assert audit.log_execution.call_args[1]["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_volume_exceeded_logs_user_id(self):
        analysis, service, adapter, audit = self._build([100000])
        user_id = uuid4()
        p1, p2 = self._patches(adapter)
        with p1, p2:
            result = await service.execute(analysis.id, self._PARAMS, user_id=user_id)

        assert result["status"] == "volume_exceeded"
        assert audit.log_execution.call_args[1]["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_cache_hit_logs_user_id_of_who_asked(self):
        """Cache hit de outro usuário grava o user_id de quem pediu, não de quem populou o cache."""
        analysis, service, adapter, audit = self._build([1, [{"valor": 1}]])
        user_a, user_b = uuid4(), uuid4()
        p1, p2 = self._patches(adapter)
        with p1, p2:
            first = await service.execute(analysis.id, self._PARAMS, user_id=user_a)
            second = await service.execute(analysis.id, self._PARAMS, user_id=user_b)

        assert first["cached"] is False and second["cached"] is True
        assert [c[1]["user_id"] for c in audit.log_execution.call_args_list] == [user_a, user_b]
