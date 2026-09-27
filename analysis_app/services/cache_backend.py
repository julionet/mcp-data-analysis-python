"""Cache Service (In-Memory) — F7_CACHE_SERVICE.md §4.4.

CacheBackend é a interface que CacheService consome; InMemoryBackend é a
única implementação em V1.0. Trocar por Redis no futuro (ambiente remoto)
significa implementar um novo CacheBackend, sem tocar em CacheService
(F7_CACHE_SERVICE.md §8.3).

NullBackend (ajuste retroativo, 2026-09-27): kill-switch global de cache —
CACHE_BACKEND=none. Nunca dá hit e nunca grava, então toda análise se
comporta como cache_frequency="none" seria por análise, sem tocar em
analyses.cache_frequency no banco. Ver F7_CACHE_SERVICE.md §7.
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class CacheBackend(ABC):
    @abstractmethod
    async def get(self, key: str) -> dict | None: ...

    @abstractmethod
    async def set(self, key: str, value: dict, ttl_seconds: int) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...


@dataclass
class _CacheEntry:
    value: dict
    expires_at: float  # time.monotonic()
    size_bytes: int


class InMemoryBackend(CacheBackend):
    """Backend local ao processo. LRU por ordem de acesso (OrderedDict),
    expiração lazy (checada em get(), varrida em set()) — F7_CACHE_SERVICE.md
    §4.2 (InMemoryBackend)."""

    def __init__(self, max_entries: int, max_size_mb: int) -> None:
        self.max_entries = max_entries
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._total_bytes = 0

    async def get(self, key: str) -> dict | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            self._remove(key)
            return None
        self._store.move_to_end(key)  # marca como mais recente (LRU)
        return entry.value

    async def set(self, key: str, value: dict, ttl_seconds: int) -> None:
        size_bytes = len(json.dumps(value, default=str).encode("utf-8"))
        if size_bytes > self.max_size_bytes:
            logger.warning(
                "Entrada de cache '%s' (%d bytes) excede CACHE_MAX_SIZE_MB — não gravada",
                key,
                size_bytes,
            )
            return

        self._purge_expired()

        if key in self._store:
            self._remove(key)

        self._store[key] = _CacheEntry(
            value=value,
            expires_at=time.monotonic() + ttl_seconds,
            size_bytes=size_bytes,
        )
        self._total_bytes += size_bytes

        while len(self._store) > self.max_entries or self._total_bytes > self.max_size_bytes:
            oldest_key = next(iter(self._store))
            self._remove(oldest_key)

    async def delete(self, key: str) -> None:
        self._remove(key)

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired_keys = [key for key, entry in self._store.items() if now > entry.expires_at]
        for key in expired_keys:
            self._remove(key)

    def _remove(self, key: str) -> None:
        entry = self._store.pop(key, None)
        if entry is not None:
            self._total_bytes -= entry.size_bytes


class NullBackend(CacheBackend):
    """CACHE_BACKEND=none — desliga o cache globalmente. get() sempre None,
    set()/delete() são no-op. Usada como kill-switch em vez de mexer em
    analyses.cache_frequency de cada análise."""

    async def get(self, key: str) -> dict | None:
        return None

    async def set(self, key: str, value: dict, ttl_seconds: int) -> None:
        pass

    async def delete(self, key: str) -> None:
        pass
