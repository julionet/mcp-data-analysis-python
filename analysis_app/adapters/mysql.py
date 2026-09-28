"""Adapter MySQL (aiomysql) — F10_MYSQL_ADAPTER.md §4.4."""

import re
import aiomysql

from adapters.base import DatabaseAdapter
from config import settings


class MySQLAdapter(DatabaseAdapter):
    async def connect(self) -> None:
        """Abre o pool de conexões MySQL com valores padrão do aiomysql."""
        self._pool = await aiomysql.create_pool(
            host=self.config["host"],
            port=self.config.get("port", 3306),
            user=self.config["user"],
            password=self.config["password"],
            db=self.config["database"],
            connect_timeout=settings.query_timeout_seconds,
            autocommit=True,
        )

    async def disconnect(self) -> None:
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()

    async def execute_query(self, query: str, params: dict | None = None, scalar: bool = False):
        """Executa query parametrizada com placeholders ? (MySQL).

        scalar=True retorna um valor escalar (ex: COUNT(*)); scalar=False
        (padrão) retorna list[dict], uma linha por dict.
        """
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                ordered_values = list((params or {}).values())
                await cursor.execute(query, ordered_values)
                if scalar:
                    row = await cursor.fetchone()
                    return row[list(row.keys())[0]] if row else None
                rows = await cursor.fetchall()
                return rows if rows else []

    async def execute(self, query: str, *args) -> None:
        """Executa INSERT/UPDATE/DELETE com parâmetros posicionais."""
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, args)
            await conn.commit()

    async def test_connection(self) -> bool:
        try:
            await self.execute_query("SELECT 1")
            return True
        except Exception:
            return False

    def translate_params(self, sql: str, param_names: list[str]) -> str:
        """Traduz placeholders nomeados (:param) para MySQL (?).

        Exemplo:
            input:  "SELECT * FROM t WHERE x = :x AND y = :y", ["x", "y"]
            output: "SELECT * FROM t WHERE x = ? AND y = ?"
        """
        translated = sql
        for name in param_names:
            translated = re.sub(rf":{re.escape(name)}\b", "?", translated)
        return translated
