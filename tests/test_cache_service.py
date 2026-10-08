"""Testes unitários da F7 — ver F7_CACHE_SERVICE.md §6.1.

TestInMemoryBackend: get/set/delete, TTL lazy, LRU (entradas e MB), oversize.
TestCacheService: chave, TTL, fluxo hit/miss/lock/double-check, Volume Guard no hit.
TestAnalysisServiceCache: integração com AnalysisService.execute() (F7_CACHE_SERVICE.md §4.2).
"""

import asyncio
import json
import logging
from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from repositories.analysis_repo import Analysis, AnalysisStep
from repositories.data_source_repo import DataSource
from schemas.exceptions import InvalidCacheFrequencyError
from services.analysis_service import AnalysisService
from services.cache_backend import InMemoryBackend, NullBackend
from services.cache_service import CacheService
from services.volume_guard_service import VolumeGuardService


class TestInMemoryBackend:
    @pytest.mark.asyncio
    async def test_set_get_roundtrip(self):
        backend = InMemoryBackend(max_entries=10, max_size_mb=10)

        await backend.set("k", {"v": 1}, ttl_seconds=1000)

        assert await backend.get("k") == {"v": 1}

    @pytest.mark.asyncio
    async def test_delete_removes_entry(self):
        backend = InMemoryBackend(max_entries=10, max_size_mb=10)
        await backend.set("k", {"v": 1}, ttl_seconds=1000)

        await backend.delete("k")

        assert await backend.get("k") is None

    @pytest.mark.asyncio
    async def test_ttl_expiration_lazy(self):
        backend = InMemoryBackend(max_entries=10, max_size_mb=10)

        # set() consome 2 chamadas a monotonic() (purge_expired + expires_at);
        # cada get() consome 1. ttl=50 a partir de t=100 -> expira em t=150.
        with patch(
            "services.cache_backend.time.monotonic",
            side_effect=[100.0, 100.0, 120.0, 200.0],
        ):
            await backend.set("k", {"v": 1}, ttl_seconds=50)
            assert await backend.get("k") == {"v": 1}  # t=120, dentro do TTL
            assert await backend.get("k") is None  # t=200, expirado

    @pytest.mark.asyncio
    async def test_lru_eviction_by_entries(self):
        backend = InMemoryBackend(max_entries=2, max_size_mb=10)

        await backend.set("a", {"v": "a"}, ttl_seconds=1000)
        await backend.set("b", {"v": "b"}, ttl_seconds=1000)
        await backend.get("a")  # "a" vira mais recente; "b" fica como LRU
        await backend.set("c", {"v": "c"}, ttl_seconds=1000)  # despeja "b"

        assert await backend.get("b") is None
        assert await backend.get("a") == {"v": "a"}
        assert await backend.get("c") == {"v": "c"}

    @pytest.mark.asyncio
    async def test_lru_eviction_by_size(self):
        value = {"payload": "x" * 200}
        entry_size = len(json.dumps(value, default=str).encode("utf-8"))
        max_size_mb = (entry_size * 2.5) / (1024 * 1024)  # cabem ~2 entradas, não 3
        backend = InMemoryBackend(max_entries=100, max_size_mb=max_size_mb)

        await backend.set("a", value, ttl_seconds=1000)
        await backend.set("b", value, ttl_seconds=1000)
        await backend.set("c", value, ttl_seconds=1000)  # excede o orçamento -> despeja "a"

        assert await backend.get("a") is None
        assert await backend.get("b") == value
        assert await backend.get("c") == value

    @pytest.mark.asyncio
    async def test_oversized_value_not_stored(self, caplog):
        value = {"payload": "x" * 1000}
        size_bytes = len(json.dumps(value, default=str).encode("utf-8"))
        max_size_mb = (size_bytes - 1) / (1024 * 1024)  # orçamento menor que o valor sozinho
        backend = InMemoryBackend(max_entries=10, max_size_mb=max_size_mb)

        with caplog.at_level(logging.WARNING):
            await backend.set("k", value, ttl_seconds=1000)

        assert await backend.get("k") is None
        assert "CACHE_MAX_SIZE_MB" in caplog.text


class TestNullBackend:
    """CACHE_BACKEND=none — kill-switch global (ajuste retroativo, 2026-09-27)."""

    @pytest.mark.asyncio
    async def test_get_always_none(self):
        backend = NullBackend()
        await backend.set("k", {"v": 1}, ttl_seconds=3600)

        assert await backend.get("k") is None

    @pytest.mark.asyncio
    async def test_get_or_execute_always_calls_executor(self):
        service = CacheService(NullBackend(), max_rows=500, max_size_kb=150)
        call_count = 0

        async def executor():
            nonlocal call_count
            call_count += 1
            return {"status": "success", "data": [1]}

        result_1 = await service.get_or_execute("k", 3600, False, executor)
        result_2 = await service.get_or_execute("k", 3600, False, executor)

        assert call_count == 2
        assert result_1["cached"] is False
        assert result_2["cached"] is False


class TestCacheService:
    def _service(self, max_rows=500, max_size_kb=150) -> CacheService:
        return CacheService(InMemoryBackend(max_entries=100, max_size_mb=10), max_rows, max_size_kb)

    def test_build_key_order_independent(self):
        service = self._service()
        analysis_id = uuid4()
        updated_at = datetime(2026, 1, 1, 12, 0, 0)

        key1 = service.build_key(analysis_id, updated_at, {"a": 1, "b": 2})
        key2 = service.build_key(analysis_id, updated_at, {"b": 2, "a": 1})

        assert key1 == key2
        assert key1.startswith(f"analysis:{analysis_id}:")

    def test_build_key_changes_with_updated_at(self):
        service = self._service()
        analysis_id = uuid4()

        key1 = service.build_key(analysis_id, datetime(2026, 1, 1), {"a": 1})
        key2 = service.build_key(analysis_id, datetime(2026, 1, 2), {"a": 1})

        assert key1 != key2

    def test_build_key_excludes_confirmar_volume_alto(self):
        """confirmar_volume_alto não é parâmetro de build_key — quem chama
        (AnalysisService) nunca o inclui no dict de params (F7_CACHE_SERVICE.md §3)."""
        service = self._service()
        analysis_id = uuid4()
        updated_at = datetime(2026, 1, 1)

        key1 = service.build_key(analysis_id, updated_at, {"a": 1})
        key2 = service.build_key(analysis_id, updated_at, {"a": 1})

        assert key1 == key2

    def test_resolve_ttl_values(self):
        assert CacheService.resolve_ttl("hourly") == 3600
        assert CacheService.resolve_ttl("daily") == 86400
        assert CacheService.resolve_ttl("weekly") == 604800
        assert CacheService.resolve_ttl("none") is None

    def test_resolve_ttl_invalid_raises(self):
        with pytest.raises(InvalidCacheFrequencyError):
            CacheService.resolve_ttl("mensal")

    @pytest.mark.asyncio
    async def test_miss_then_hit(self):
        service = self._service()
        call_count = 0

        async def executor():
            nonlocal call_count
            call_count += 1
            return {"status": "success", "data": [{"x": 1}]}

        result_1 = await service.get_or_execute("k", 3600, False, executor)
        result_2 = await service.get_or_execute("k", 3600, False, executor)

        assert call_count == 1
        assert result_1["cached"] is False
        assert result_2["cached"] is True
        assert result_1["data"] == result_2["data"] == [{"x": 1}]

    @pytest.mark.asyncio
    async def test_success_only_is_cached(self):
        service = self._service()
        call_count = 0

        async def executor():
            nonlocal call_count
            call_count += 1
            return {"status": "volume_exceeded", "mensagem": "grande demais"}

        result_1 = await service.get_or_execute("k", 3600, False, executor)
        result_2 = await service.get_or_execute("k", 3600, False, executor)

        assert call_count == 2  # nunca cacheado -> executor roda de novo
        assert result_1["cached"] is False
        assert result_2["cached"] is False

    @pytest.mark.asyncio
    async def test_concurrent_identical_requests_single_execution(self):
        service = self._service()
        call_count = 0

        async def executor():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return {"status": "success", "data": [1, 2, 3]}

        result_1, result_2 = await asyncio.wait_for(
            asyncio.gather(
                service.get_or_execute("k", 3600, False, executor),
                service.get_or_execute("k", 3600, False, executor),
            ),
            timeout=2,
        )

        assert call_count == 1
        assert result_1["data"] == result_2["data"] == [1, 2, 3]
        assert {result_1["cached"], result_2["cached"]} == {True, False}

    @pytest.mark.asyncio
    async def test_lock_released_on_executor_exception(self):
        service = self._service()

        async def failing_executor():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await asyncio.wait_for(
                service.get_or_execute("k", 3600, False, failing_executor), timeout=2
            )

        async def good_executor():
            return {"status": "success", "data": [1]}

        result = await asyncio.wait_for(
            service.get_or_execute("k", 3600, False, good_executor), timeout=2
        )

        assert result == {"status": "success", "data": [1], "cached": False}

    @pytest.mark.asyncio
    async def test_large_hit_without_confirmation_returns_volume_exceeded(self):
        service = self._service(max_rows=500, max_size_kb=150)
        key = "analysis:teste:grande"
        await service.backend.set(
            key,
            {
                "resultado": {"status": "success", "data": [{"x": 1}] * 8400},
                "linhas": 8400,
                "tamanho_kb": 510.0,
                "gravado_em": "2026-01-01T00:00:00-03:00",
            },
            ttl_seconds=3600,
        )

        async def executor():
            raise AssertionError("BD não deveria ser tocado em um hit")

        result = await service.get_or_execute(key, 3600, False, executor)

        assert result["status"] == "volume_exceeded"
        assert result["estimativa"] == {"linhas": 8400, "tamanho_estimado_kb": 510.0}
        assert result["limite"] == {"linhas": 500, "tamanho_kb": 150}
        assert result["cached"] is False

    @pytest.mark.asyncio
    async def test_large_hit_with_confirmation_returns_aviso(self):
        service = self._service(max_rows=500, max_size_kb=150)
        key = "analysis:teste:grande"
        await service.backend.set(
            key,
            {
                "resultado": {
                    "status": "success",
                    "data": [{"x": 1}] * 8400,
                    "aviso": "resultado grande, enviado por confirmação explícita",
                },
                "linhas": 8400,
                "tamanho_kb": 510.0,
                "gravado_em": "2026-01-01T00:00:00-03:00",
            },
            ttl_seconds=3600,
        )

        async def executor():
            raise AssertionError("BD não deveria ser tocado em um hit")

        result = await service.get_or_execute(key, 3600, True, executor)

        assert result["status"] == "success"
        assert result["cached"] is True
        assert result["aviso"] == "resultado grande, enviado por confirmação explícita"


VENDAS_PARAMETERS = {
    "data_inicial": {"type": "date", "required": True, "description": "..."},
}
VENDAS_SQL = "SELECT data, valor FROM vendas WHERE data = :data_inicial"


def _make_analysis(cache_frequency: str) -> Analysis:
    return Analysis(
        id=uuid4(),
        name="vendas_por_periodo",
        description="Vendas por periodo",
        data_source_id=uuid4(),
        parameters=VENDAS_PARAMETERS,
        is_active=True,
        updated_at=datetime(2026, 1, 1, 12, 0, 0),
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
        definition={"sql": VENDAS_SQL, "params": ["data_inicial"]},
    )


class TestAnalysisServiceCache:
    def _service(self, analysis_repo, data_source_repo) -> AnalysisService:
        return AnalysisService(
            analysis_repo,
            data_source_repo,
            VolumeGuardService(max_rows=500, max_size_kb=150),
            CacheService(InMemoryBackend(max_entries=100, max_size_mb=10), max_rows=500, max_size_kb=150),
            AsyncMock(),  # audit_service
        )

    @pytest.mark.asyncio
    async def test_cache_frequency_none_bypasses_cache(self):
        analysis = _make_analysis(cache_frequency="none")
        data_source = _make_data_source(analysis)
        step = _make_step(analysis)

        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [step]
        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = data_source

        fake_adapter = AsyncMock()
        fake_adapter.execute_query.side_effect = [1, [{"data": "x"}], 1, [{"data": "x"}]]

        service = self._service(analysis_repo, data_source_repo)

        with (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
            patch("services.analysis_service.decrypt_password", return_value="senha"),
        ):
            result_1 = await service.execute(analysis.id, {"data_inicial": "2026-01-01"})
            result_2 = await service.execute(analysis.id, {"data_inicial": "2026-01-01"})

        assert result_1["cached"] is False
        assert result_2["cached"] is False
        assert fake_adapter.execute_query.await_count == 4  # COUNT+SELECT em cada chamada

    @pytest.mark.asyncio
    async def test_invalid_cache_frequency_returns_error_without_query(self):
        analysis = _make_analysis(cache_frequency="mensal")
        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        data_source_repo = AsyncMock()

        service = self._service(analysis_repo, data_source_repo)

        result = await service.execute(analysis.id, {"data_inicial": "2026-01-01"})

        assert result["status"] == "error"
        assert result["cached"] is False
        assert "hourly" in result["mensagem"] and "daily" in result["mensagem"]
        data_source_repo.get_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_cached_flag_in_payload(self):
        analysis = _make_analysis(cache_frequency="daily")
        data_source = _make_data_source(analysis)
        step = _make_step(analysis)

        analysis_repo = AsyncMock()
        analysis_repo.get_by_id.return_value = analysis
        analysis_repo.get_steps.return_value = [step]
        data_source_repo = AsyncMock()
        data_source_repo.get_by_id.return_value = data_source

        fake_adapter = AsyncMock()
        fake_adapter.execute_query.side_effect = [1, [{"data": "x"}]]

        service = self._service(analysis_repo, data_source_repo)

        with (
            patch("services.analysis_service.AdapterFactory.create_adapter", return_value=fake_adapter),
            patch("services.analysis_service.decrypt_password", return_value="senha"),
        ):
            result_1 = await service.execute(analysis.id, {"data_inicial": "2026-01-01"})
            result_2 = await service.execute(analysis.id, {"data_inicial": "2026-01-01"})

        assert result_1["cached"] is False
        assert result_2["cached"] is True
        assert fake_adapter.execute_query.await_count == 2  # 2ª chamada não tocou o BD


class TestCacheServiceLockCleanup:
    @pytest.mark.asyncio
    async def test_locks_dict_is_empty_after_execution(self):
        service = CacheService(InMemoryBackend(max_entries=100, max_size_mb=10), 500, 150)

        async def executor():
            return {"status": "success", "data": [1]}

        await service.get_or_execute("k1", 3600, False, executor)
        await service.get_or_execute("k2", 3600, False, executor)

        assert service._locks == {}

    @pytest.mark.asyncio
    async def test_locks_dict_is_empty_after_executor_exception(self):
        service = CacheService(InMemoryBackend(max_entries=100, max_size_mb=10), 500, 150)

        async def failing_executor():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await service.get_or_execute("k", 3600, False, failing_executor)

        assert service._locks == {}


class TestInMemoryBackendEdges:
    """F17 M1 — substituição de chave existente, purga de expirados e contabilidade de bytes."""

    @pytest.mark.asyncio
    async def test_set_on_existing_key_replaces_value_and_adjusts_total_bytes(self):
        backend = InMemoryBackend(max_entries=10, max_size_mb=1)
        await backend.set("k", {"v": "a"}, 60)
        small = backend._total_bytes
        await backend.set("k", {"v": "a" * 100}, 60)

        assert (await backend.get("k")) == {"v": "a" * 100}
        assert len(backend._store) == 1
        assert backend._total_bytes > small  # não somou o valor antigo junto

    @pytest.mark.asyncio
    async def test_expired_entries_are_purged_on_next_set_and_free_their_bytes(self):
        backend = InMemoryBackend(max_entries=10, max_size_mb=1)
        with patch("services.cache_backend.time.monotonic", return_value=1000.0):
            await backend.set("old", {"v": "x" * 50}, 10)
        with patch("services.cache_backend.time.monotonic", return_value=2000.0):
            await backend.set("new", {"v": 1}, 10)

        assert list(backend._store) == ["new"]
        assert backend._total_bytes == backend._store["new"].size_bytes

    @pytest.mark.asyncio
    async def test_delete_removes_entry_and_missing_key_is_noop(self):
        backend = InMemoryBackend(max_entries=10, max_size_mb=1)
        await backend.set("k", {"v": 1}, 60)

        await backend.delete("k")
        await backend.delete("inexistente")

        assert await backend.get("k") is None and backend._total_bytes == 0

    @pytest.mark.asyncio
    async def test_null_backend_delete_is_a_safe_noop(self):
        backend = NullBackend()
        await backend.set("k", {"v": 1}, 60)
        await backend.delete("k")

        assert await backend.get("k") is None
