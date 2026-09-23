"""Adapter PostgreSQL (asyncpg) — F2_POSTGRESQL_ADAPTER.md §4.4."""

import asyncpg

from adapters.base import DatabaseAdapter


class PostgreSQLAdapter(DatabaseAdapter):
    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            host=self.config["host"],
            port=self.config["port"],
            user=self.config["user"],
            password=self.config["password"],
            database=self.config["database"],
        )  # min_size/max_size/timeout = defaults do asyncpg

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()

    async def execute_query(self, query: str, params: dict | None = None, scalar: bool = False):
        async with self._pool.acquire() as conn:
            if scalar:
                return await conn.fetchval(query, *(params or {}).values())
            records = await conn.fetch(query, *(params or {}).values())
            return [dict(r) for r in records]

    async def test_connection(self) -> bool:
        try:
            await self.execute_query("SELECT 1")
            return True
        except Exception:
            return False
