"""Testes unitários da F3 — ver F3_CONTROLE_VOLUME.md §6.1."""

from unittest.mock import AsyncMock

import pytest

from schemas.exceptions import VolumeExceededError
from services.volume_guard_service import VolumeGuardService


class TestVolumeGuardService:
    @pytest.mark.asyncio
    async def test_check_row_count_within_limit(self):
        adapter = AsyncMock()
        adapter.execute_query.return_value = 300
        service = VolumeGuardService(max_rows=500, max_size_kb=150)

        result = await service.check_row_count(adapter, "SELECT COUNT(*)...", {})

        assert result == 300
        adapter.execute_query.assert_awaited_once_with("SELECT COUNT(*)...", {}, scalar=True)

    @pytest.mark.asyncio
    async def test_check_row_count_exceeds_limit_raises(self):
        adapter = AsyncMock()
        adapter.execute_query.return_value = 8400
        service = VolumeGuardService(max_rows=500, max_size_kb=150)

        with pytest.raises(VolumeExceededError) as exc:
            await service.check_row_count(adapter, "SELECT COUNT(*)...", {})

        assert exc.value.estimated_rows == 8400

    def test_check_serialized_size_within_limit(self):
        service = VolumeGuardService(max_rows=500, max_size_kb=150)

        result = service.check_serialized_size([{"a": 1}] * 10)

        assert result < 150

    def test_check_serialized_size_exceeds_limit_raises(self):
        service = VolumeGuardService(max_rows=500, max_size_kb=1)
        big_result = [{"col": "x" * 1000}] * 100

        with pytest.raises(VolumeExceededError):
            service.check_serialized_size(big_result)

    def test_build_refinement_response_format(self):
        service = VolumeGuardService(max_rows=500, max_size_kb=150)
        error = VolumeExceededError(estimated_rows=8400, estimated_size_kb=510)

        response = service.build_refinement_response(error)

        assert response["status"] == "volume_exceeded"
        assert response["estimativa"] == {"linhas": 8400, "tamanho_estimado_kb": 510}
        assert response["limite"] == {"linhas": 500, "tamanho_kb": 150}
        assert "8400" in response["mensagem"]
        assert "confirmar_volume_alto=true" in response["mensagem"]
