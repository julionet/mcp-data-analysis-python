"""Adapter PostgreSQL (asyncpg) — F2_POSTGRESQL_ADAPTER.md §4.4."""

import re
import asyncpg

from adapters.base import DatabaseAdapter
from config import settings


class PostgreSQLAdapter(DatabaseAdapter):
    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            host=self.config["host"],
            port=self.config["port"],
            user=self.config["user"],
            password=self.config["password"],
            database=self.config["database"],
            command_timeout=settings.query_timeout_seconds,
        )  # min_size/max_size = defaults do asyncpg; command_timeout via .env (ajuste
        # retroativo F4, 2026-09-26 — ver ARQUITETURA.md §8.1 / F4_EXECUTION_ENGINE.md)

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()

    async def execute_query(self, query: str, params: dict | None = None, scalar: bool = False):
        async with self._pool.acquire() as conn:
            if scalar:
                return await conn.fetchval(query, *(params or {}).values())
            records = await conn.fetch(query, *(params or {}).values())
            return [dict(r) for r in records]

    async def execute(self, query: str, *args) -> None:
        """Executa INSERT/UPDATE/DELETE com parâmetros posicionais."""
        async with self._pool.acquire() as conn:
            await conn.execute(query, *args)

    async def test_connection(self) -> bool:
        try:
            await self.execute_query("SELECT 1")
            return True
        except Exception:
            return False

    def translate_params(self, sql: str, param_names: list[str]) -> str:
        """Traduz placeholders nomeados (:param) para PostgreSQL ($1, $2, ...)."""
        translated = sql
        for index, name in enumerate(param_names, start=1):
            translated = re.sub(rf":{re.escape(name)}\b", f"${index}", translated)
        return translated
