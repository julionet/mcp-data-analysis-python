"""Testes unitários da F14 — AnalysisService: error_code/retryable, status 'timeout' e
retry só de falha rápida de conexão (F14_ERROR_HANDLING_VALIDATION.md §4.2/§4.3/§5)."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from config import settings
from services.audit_service import AuditService
from tests.helpers import make_fake_adapter
from tests.test_analysis_service import (
    _make_analysis,
    _make_data_source,
    _make_step,
    _service,
)

PARAMS = {"data_inicial": "2026-01-01", "data_final": "2026-01-31"}
DATASET = [{"data": "2026-01-05", "valor": 100.0, "pago": True}]


async def _run(fake_adapter, *, params=None, confirmar=False, data_source_tweak=None, steps=None):
    """Executa uma análise com o adapter fake e devolve (resultado, audit_service, service)."""
    analysis = _make_analysis()
    data_source = _make_data_source(analysis)
    if data_source_tweak:
        data_source_tweak(data_source)

    analysis_repo = AsyncMock()
    analysis_repo.get_by_id.return_value = analysis
    analysis_repo.get_steps.return_value = [_make_step(analysis)] if steps is None else steps
    data_source_repo = AsyncMock()
    data_source_repo.get_by_id.return_value = data_source
    audit_service = AsyncMock()
    service = _service(analysis_repo, data_source_repo, audit_service=audit_service)

    with (
        patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
        patch("services.analysis_service.decrypt_password", return_value="senha_decifrada"),
        patch("services.retry.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        result = await service.execute(analysis.id, PARAMS if params is None else params, confirmar)
    return result, audit_service, sleep


def _assert_error(result, code, retryable):
    assert result["status"] == "error"
    assert result["error_code"] == code
    assert result["retryable"] is retryable
    assert result["cached"] is False


class TestErrorCodes:
    @pytest.mark.asyncio
    async def test_invalid_parameters(self):
        result, audit, _ = await _run(make_fake_adapter(), params={"data_final": "2026-01-31"})

        _assert_error(result, "INVALID_PARAMETERS", False)
        kwargs = audit.log_execution.await_args.kwargs
        assert kwargs["status"] == "error"
        assert kwargs["error_code"] == "INVALID_PARAMETERS"  # o histórico guarda o mesmo código da resposta

    @pytest.mark.asyncio
    async def test_analysis_not_found(self):
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = None

        result = await _service(analysis_repo).execute(uuid4(), {})

        _assert_error(result, "ANALYSIS_NOT_FOUND", False)

    @pytest.mark.asyncio
    async def test_analysis_without_steps_is_invalid_config(self):
        result, _, _ = await _run(make_fake_adapter(), steps=[])

        _assert_error(result, "INVALID_ANALYSIS_CONFIG", False)

    @pytest.mark.asyncio
    async def test_inactive_data_source_is_unavailable(self):
        result, _, _ = await _run(
            make_fake_adapter(), data_source_tweak=lambda ds: setattr(ds, "is_active", False)
        )

        _assert_error(result, "DATA_SOURCE_UNAVAILABLE", True)

    @pytest.mark.asyncio
    async def test_unexpected_error_is_internal_error(self):
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.side_effect = RuntimeError("bug")

        result = await _service(analysis_repo).execute(uuid4(), {})

        _assert_error(result, "INTERNAL_ERROR", False)
        assert result["mensagem"] == "Erro interno ao executar a análise."

    @pytest.mark.asyncio
    async def test_success_and_volume_exceeded_have_no_error_fields(self):
        adapter = make_fake_adapter()
        adapter.execute_query.side_effect = [1, DATASET]
        ok, _, _ = await _run(adapter)

        adapter = make_fake_adapter()
        adapter.execute_query.return_value = 8400
        exceeded, _, _ = await _run(adapter)

        assert ok == {"status": "success", "data": DATASET, "cached": False}
        assert exceeded["status"] == "volume_exceeded"
        assert "error_code" not in exceeded and "retryable" not in exceeded


class TestQueryErrors:
    @pytest.mark.asyncio
    async def test_query_timeout_is_logged_as_timeout_and_not_retried(self):
        adapter = make_fake_adapter()
        adapter.execute_query.side_effect = [1, TimeoutError("command_timeout")]
        adapter.is_timeout_error = MagicMock(return_value=True)

        result, audit, sleep = await _run(adapter)

        _assert_error(result, "QUERY_TIMEOUT", True)
        assert f"{settings.query_timeout_seconds}s" in result["mensagem"]
        assert adapter.execute_query.await_count == 2  # COUNT + SELECT, sem repetição
        sleep.assert_not_awaited()
        kwargs = audit.log_execution.await_args.kwargs
        assert kwargs["status"] == "timeout"
        assert kwargs["error_message"] == result["mensagem"]
        assert kwargs["error_code"] == "QUERY_TIMEOUT"

    @pytest.mark.asyncio
    async def test_sql_error_is_query_failed_and_not_retried(self):
        adapter = make_fake_adapter()
        adapter.execute_query.side_effect = [1, RuntimeError("syntax error near 'FORM' host=db1")]

        result, audit, sleep = await _run(adapter)

        _assert_error(result, "QUERY_FAILED", False)
        assert "syntax" not in result["mensagem"] and "db1" not in result["mensagem"]
        assert adapter.execute_query.await_count == 2
        sleep.assert_not_awaited()
        kwargs = audit.log_execution.await_args.kwargs
        assert kwargs["status"] == "error"
        assert kwargs["error_code"] == "QUERY_FAILED"

    @pytest.mark.asyncio
    async def test_error_is_not_cached(self):
        analysis = _make_analysis()
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [_make_step(analysis)]
        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = _make_data_source(analysis)
        adapter = make_fake_adapter()
        adapter.execute_query.side_effect = [1, RuntimeError("falhou"), 1, DATASET]
        service = _service(analysis_repo, data_source_repo)

        with (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=adapter),
            patch("services.analysis_service.decrypt_password", return_value="x"),
        ):
            first = await service.execute(analysis.id, PARAMS)
            second = await service.execute(analysis.id, PARAMS)

        assert first["status"] == "error"
        assert second == {"status": "success", "data": DATASET, "cached": False}


class TestRetry:
    @pytest.mark.asyncio
    async def test_connect_retries_transient_failures_until_success(self):
        adapter = make_fake_adapter()
        adapter.connect.side_effect = [ConnectionRefusedError(), ConnectionResetError(), None]
        adapter.is_transient_error = MagicMock(side_effect=lambda e: isinstance(e, ConnectionError))
        adapter.execute_query.side_effect = [1, DATASET]

        result, _, sleep = await _run(adapter)

        assert result["status"] == "success"
        assert adapter.connect.await_count == 3
        assert [c.args[0] for c in sleep.await_args_list] == [0.2, 0.4]

    @pytest.mark.asyncio
    async def test_connect_exhausted_is_data_source_unavailable(self):
        adapter = make_fake_adapter()
        adapter.connect.side_effect = ConnectionRefusedError("db1.interno:5432 password=Senha123")
        adapter.is_transient_error = MagicMock(return_value=True)

        result, audit, _ = await _run(adapter)

        _assert_error(result, "DATA_SOURCE_UNAVAILABLE", True)
        assert adapter.connect.await_count == settings.query_retry_max_attempts
        assert "Senha123" not in result["mensagem"] and "db1" not in result["mensagem"]
        kwargs = audit.log_execution.await_args.kwargs
        assert kwargs["status"] == "error"
        assert kwargs["error_code"] == "DATA_SOURCE_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_connect_non_transient_failure_is_not_retried(self):
        adapter = make_fake_adapter()
        adapter.connect.side_effect = RuntimeError("password authentication failed")

        result, _, sleep = await _run(adapter)

        _assert_error(result, "DATA_SOURCE_UNAVAILABLE", True)
        adapter.connect.assert_awaited_once()
        sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_count_query_retries_transient_failure(self):
        adapter = make_fake_adapter()
        adapter.execute_query.side_effect = [ConnectionResetError(), 1, DATASET]
        adapter.is_transient_error = MagicMock(side_effect=lambda e: isinstance(e, ConnectionError))

        result, _, sleep = await _run(adapter)

        assert result["status"] == "success"
        assert adapter.execute_query.await_count == 3  # COUNT (falha) + COUNT + SELECT
        assert [c.args[0] for c in sleep.await_args_list] == [0.2]

    @pytest.mark.asyncio
    async def test_main_query_exhausts_transient_retries(self):
        adapter = make_fake_adapter()
        adapter.is_transient_error = MagicMock(side_effect=lambda e: isinstance(e, ConnectionError))
        adapter.execute_query.side_effect = [1] + [ConnectionResetError()] * settings.query_retry_max_attempts

        result, _, _ = await _run(adapter)

        _assert_error(result, "DATA_SOURCE_UNAVAILABLE", True)
        assert adapter.execute_query.await_count == 1 + settings.query_retry_max_attempts

    @pytest.mark.asyncio
    async def test_volume_exceeded_does_not_trigger_retry(self):
        adapter = make_fake_adapter()
        adapter.is_transient_error = MagicMock(return_value=True)  # mesmo "transitório" para tudo
        adapter.execute_query.return_value = 8400

        result, _, sleep = await _run(adapter)

        assert result["status"] == "volume_exceeded"
        assert adapter.execute_query.await_count == 1
        sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retry_disabled_with_single_attempt(self):
        adapter = make_fake_adapter()
        adapter.connect.side_effect = ConnectionRefusedError()
        adapter.is_transient_error = MagicMock(return_value=True)

        with patch.object(settings, "query_retry_max_attempts", 1):
            result, _, sleep = await _run(adapter)

        _assert_error(result, "DATA_SOURCE_UNAVAILABLE", True)
        adapter.connect.assert_awaited_once()
        sleep.assert_not_awaited()


class TestAuditTimeoutStatus:
    @pytest.mark.asyncio
    async def test_timeout_status_keeps_error_message(self):
        repo = AsyncMock()

        await AuditService(repo).log_execution(
            analysis_id=uuid4(),
            parameters={},
            status="timeout",
            execution_time_ms=30012,
            cached=False,
            error_message="A consulta excedeu o tempo limite de 30s.",
            error_code="QUERY_TIMEOUT",
        )

        kwargs = repo.create.await_args.kwargs
        assert kwargs["status"] == "timeout"
        assert kwargs["error_message"] == "A consulta excedeu o tempo limite de 30s."
        assert kwargs["execution_time_ms"] == 30012
        assert kwargs["error_code"] == "QUERY_TIMEOUT"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["success", "volume_exceeded"])
    async def test_error_code_is_dropped_when_there_is_no_error(self, status):
        repo = AsyncMock()

        await AuditService(repo).log_execution(
            analysis_id=uuid4(), parameters={}, status=status, execution_time_ms=5, cached=False,
            result={"status": status, "data": [], "estimativa": {}}, error_code="QUERY_FAILED",
        )

        assert repo.create.await_args.kwargs["error_code"] is None

    @pytest.mark.asyncio
    async def test_internal_error_in_execute_is_recorded_as_internal_error(self):
        # exceção fora dos erros de domínio, dentro do try de _execute (aqui: cache_service quebra)
        analysis = _make_analysis()
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        audit = AsyncMock()
        cache = MagicMock()
        cache.build_key.side_effect = RuntimeError("bug no cache")
        service = _service(analysis_repo, audit_service=audit, cache_service=cache)

        result = await service.execute(analysis.id, PARAMS)

        _assert_error(result, "INTERNAL_ERROR", False)
        kwargs = audit.log_execution.await_args.kwargs
        assert kwargs["status"] == "error" and kwargs["error_code"] == "INTERNAL_ERROR"

    @pytest.mark.asyncio
    async def test_success_status_drops_error_message(self):
        repo = AsyncMock()

        await AuditService(repo).log_execution(
            analysis_id=uuid4(), parameters={}, status="success", execution_time_ms=5,
            cached=False, result={"status": "success", "data": []}, error_message="ignorado",
        )

        assert repo.create.await_args.kwargs["error_message"] is None
