"""Cache Service (In-Memory) — F7_CACHE_SERVICE.md §4.2/§4.4.

CacheService monta a chave, resolve o TTL, e implementa o fluxo hit/miss/
lock/double-check descrito na spec. Não conhece Postgres nem o Volume Guard
(F3) diretamente — apenas reaplica os limites (max_rows/max_size_kb) sobre
o que já está guardado na entrada de cache, para nunca contornar o Volume
Guard em um cache hit.
"""

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID

from schemas.exceptions import InvalidCacheFrequencyError
from services.cache_backend import CacheBackend

logger = logging.getLogger(__name__)

_TTL_BY_FREQUENCY: dict[str, int | None] = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
    "none": None,
}


class CacheService:
    def __init__(self, backend: CacheBackend, max_rows: int, max_size_kb: int) -> None:
        self.backend = backend
        self.max_rows = max_rows
        self.max_size_kb = max_size_kb
        self._locks: dict[str, asyncio.Lock] = {}

    def build_key(self, analysis_id: UUID, updated_at: datetime, params: dict) -> str:
        """analysis:<id>:<sha256(updated_at|params normalizados)> —
        F7_CACHE_SERVICE.md §4.2 (Chave do cache)."""
        normalized_params = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
        payload = f"{updated_at.isoformat()}|{normalized_params}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"analysis:{analysis_id}:{digest}"

    @staticmethod
    def resolve_ttl(cache_frequency: str) -> int | None:
        """Retorna segundos, None para 'none'. Levanta InvalidCacheFrequencyError
        para valor desconhecido — F7_CACHE_SERVICE.md §4.2 (Mapa de TTL)."""
        if cache_frequency not in _TTL_BY_FREQUENCY:
            raise InvalidCacheFrequencyError(
                f"cache_frequency '{cache_frequency}' inválido — "
                f"valores aceitos: {', '.join(_TTL_BY_FREQUENCY)}"
            )
        return _TTL_BY_FREQUENCY[cache_frequency]

    async def get_or_execute(
        self,
        key: str,
        ttl_seconds: int,
        confirmar_volume_alto: bool,
        executor: Callable[[], Awaitable[dict]],
    ) -> dict:
        """Fluxo hit/miss/lock/double-check — F7_CACHE_SERVICE.md §4.2."""
        entry = await self.backend.get(key)
        if entry is not None:
            return self._handle_hit(key, entry, confirmar_volume_alto)

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            entry = await self.backend.get(key)  # double-check
            if entry is not None:
                return self._handle_hit(key, entry, confirmar_volume_alto)

            logger.info("Cache MISS - executando a query (chave=%s)", key)
            result = await executor()
            if result.get("status") == "success":
                await self._store(key, result, ttl_seconds)
            return {**result, "cached": False}

    async def _store(self, key: str, result: dict, ttl_seconds: int) -> None:
        dataset = result.get("data", [])
        tamanho_kb = len(json.dumps(dataset, default=str).encode("utf-8")) / 1024
        entry = {
            "resultado": result,
            "linhas": len(dataset),
            "tamanho_kb": tamanho_kb,
            "gravado_em": datetime.now().astimezone().isoformat(),
        }
        await self.backend.set(key, entry, ttl_seconds)

    def _handle_hit(self, key: str, entry: dict, confirmar_volume_alto: bool) -> dict:
        linhas = entry["linhas"]
        tamanho_kb = entry["tamanho_kb"]
        excede_limite = linhas > self.max_rows or tamanho_kb > self.max_size_kb

        if not excede_limite:
            logger.info(
                "Cache HIT - %d linha(s), %.1fKB, gravado em %s (chave=%s)",
                linhas, tamanho_kb, entry["gravado_em"], key,
            )
            return {**entry["resultado"], "cached": True}

        if confirmar_volume_alto:
            logger.info(
                "Cache HIT (grande, confirmar_volume_alto=true) - %d linha(s), %.1fKB (chave=%s)",
                linhas, tamanho_kb, key,
            )
            return {**entry["resultado"], "cached": True}

        logger.info(
            "Cache HIT porem volume excede o limite (%d linhas/%.1fKB > %d/%dKB) sem "
            "confirmar_volume_alto - devolvendo volume_exceeded sem tocar o BD (chave=%s)",
            linhas, tamanho_kb, self.max_rows, self.max_size_kb, key,
        )
        return {
            "status": "volume_exceeded",
            "estimativa": {"linhas": linhas, "tamanho_estimado_kb": tamanho_kb},
            "limite": {"linhas": self.max_rows, "tamanho_kb": self.max_size_kb},
            "mensagem": (
                f"O resultado em cache tem aproximadamente {linhas} linhas "
                f"(~{tamanho_kb:.1f}KB), acima do limite de {self.max_rows} linhas / "
                f"{self.max_size_kb}KB. Refine o período ou adicione filtros (ex: região, produto). "
                f"Se quiser continuar mesmo assim, chame novamente com confirmar_volume_alto=true — "
                f"atenção: isso pode consumir um volume alto de tokens."
            ),
            "cached": False,
        }
