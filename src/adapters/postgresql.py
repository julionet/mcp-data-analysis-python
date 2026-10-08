"""Adapter PostgreSQL (asyncpg) — F2_POSTGRESQL_ADAPTER.md §4.4."""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

from adapters.base import DatabaseAdapter
from config import settings


class Transaction:
    """Conexão dentro de uma transação, com a mesma semântica de execute_query()/execute()."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def execute_query(self, query: str, params: dict | None = None, scalar: bool = False):
        if scalar:
            return await self._conn.fetchval(query, *(params or {}).values())
        records = await self._conn.fetch(query, *(params or {}).values())
        return [dict(r) for r in records]

    async def execute(self, query: str, *args) -> None:
        await self._conn.execute(query, *args)


class PostgreSQLAdapter(DatabaseAdapter):
    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            host=self.config["host"],
            port=self.config["port"],
            user=self.config["user"],
            password=self.config["password"],
            database=self.config["database"],
            command_timeout=settings.query_timeout_seconds,
            # F15: pool_min_size/pool_max_size no connection_config sobrepõem o .env (por data source)
            min_size=self.config.get("pool_min_size", settings.pg_pool_min_size),
            max_size=self.config.get("pool_max_size", settings.pg_pool_max_size),
        )  # command_timeout via .env (ajuste retroativo F4, 2026-09-26 — ver
        # ARQUITETURA.md §8.1 / F4_EXECUTION_ENGINE.md)

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

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Transaction]:
        """Commit ao sair do bloco; rollback (e a exceção propaga) se ele levantar."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                yield Transaction(conn)

    async def test_connection(self) -> bool:
        try:
            await self.execute_query("SELECT 1")
            return True
        except Exception:
            return False

    def is_timeout_error(self, exc: Exception) -> bool:
        # command_timeout do asyncpg estoura como TimeoutError; 57014 = cancelado pelo servidor
        return isinstance(exc, (TimeoutError, asyncpg.QueryCanceledError))

    def is_transient_error(self, exc: Exception) -> bool:
        return isinstance(
            exc,
            (
                ConnectionError,  # recusada/resetada pelo SO
                asyncpg.PostgresConnectionError,  # 08xxx (conexão perdida/inexistente)
                asyncpg.CannotConnectNowError,  # 57P03 (servidor subindo)
                asyncpg.TooManyConnectionsError,  # 53300
                asyncpg.AdminShutdownError,  # 57P01
                asyncpg.CrashShutdownError,  # 57P02
            ),
        )

    def translate_params(self, sql: str, param_names: list[str]) -> str:
        """Traduz placeholders nomeados (:param) para PostgreSQL ($1, $2, ...)."""
        translated = sql
        for index, name in enumerate(param_names, start=1):
            translated = re.sub(rf":{re.escape(name)}\b", f"${index}", translated)
        return translated
