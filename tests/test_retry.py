"""Testes unitários da F14 — retry_async (spec §4.3)."""

from unittest.mock import AsyncMock, patch

import pytest

from services.retry import retry_async


def _always(_exc: Exception) -> bool:
    return True


class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt_does_not_sleep(self):
        fn = AsyncMock(return_value="ok")
        with patch("services.retry.asyncio.sleep", new=AsyncMock()) as sleep:
            result = await retry_async(fn, attempts=3, base_ms=200, is_retryable=_always)

        assert result == "ok"
        fn.assert_awaited_once()
        sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_success_on_third_attempt_uses_exponential_backoff(self):
        fn = AsyncMock(side_effect=[ConnectionError("a"), ConnectionError("b"), "ok"])
        with patch("services.retry.asyncio.sleep", new=AsyncMock()) as sleep:
            result = await retry_async(fn, attempts=3, base_ms=200, is_retryable=_always)

        assert result == "ok"
        assert fn.await_count == 3
        assert [c.args[0] for c in sleep.await_args_list] == [0.2, 0.4]

    @pytest.mark.asyncio
    async def test_exhausted_attempts_reraises_last_exception(self):
        fn = AsyncMock(side_effect=[ConnectionError("1"), ConnectionError("2"), ConnectionError("3")])
        with patch("services.retry.asyncio.sleep", new=AsyncMock()) as sleep:
            with pytest.raises(ConnectionError, match="3"):
                await retry_async(fn, attempts=3, base_ms=200, is_retryable=_always)

        assert fn.await_count == 3
        assert sleep.await_count == 2  # sem espera depois da última tentativa

    @pytest.mark.asyncio
    async def test_non_retryable_exception_is_raised_immediately(self):
        fn = AsyncMock(side_effect=ValueError("sql inválido"))
        with patch("services.retry.asyncio.sleep", new=AsyncMock()) as sleep:
            with pytest.raises(ValueError):
                await retry_async(
                    fn, attempts=3, base_ms=200, is_retryable=lambda e: isinstance(e, ConnectionError)
                )

        fn.assert_awaited_once()
        sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_attempts_one_means_no_retry(self):
        fn = AsyncMock(side_effect=ConnectionError("x"))
        with patch("services.retry.asyncio.sleep", new=AsyncMock()) as sleep:
            with pytest.raises(ConnectionError):
                await retry_async(fn, attempts=1, base_ms=200, is_retryable=_always)

        fn.assert_awaited_once()
        sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_attempts_below_one_is_rejected(self):
        with pytest.raises(ValueError):
            await retry_async(AsyncMock(), attempts=0, base_ms=200, is_retryable=_always)
