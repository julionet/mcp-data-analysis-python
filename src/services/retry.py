"""Retry com backoff exponencial — F14_ERROR_HANDLING_VALIDATION.md §4.3.

Só para operações idempotentes (SELECT, validado por validate_select_only) e só quando
`is_retryable(exc)` diz que a falha é transitória (conexão). Nunca repetir DML.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    base_ms: int,
    is_retryable: Callable[[Exception], bool],
    label: str = "",
) -> T:
    """Executa `fn()` até `attempts` vezes (total, não "retries extras").

    Espera `base_ms * 2^(n-1)` ms depois da tentativa n (200 ms, 400 ms com os padrões).
    Relança a última exceção quando esgota ou quando `is_retryable` é falso.
    `label` identifica a operação no log (ex.: análise/data source); só o NOME do tipo
    da exceção é logado, para não vazar host/usuário do driver.
    """
    if attempts < 1:
        raise ValueError("attempts deve ser >= 1")

    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except Exception as exc:
            if attempt == attempts or not is_retryable(exc):
                raise
            delay_ms = base_ms * 2 ** (attempt - 1)
            logger.warning(
                "Tentativa %d/%d falhou (%s)%s; nova tentativa em %d ms",
                attempt,
                attempts,
                type(exc).__name__,
                f" [{label}]" if label else "",
                delay_ms,
            )
            await asyncio.sleep(delay_ms / 1000)
