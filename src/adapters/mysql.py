"""Adapter MySQL (aiomysql) — F10_MYSQL_ADAPTER.md §4.4."""

import re
import aiomysql

from adapters.base import DatabaseAdapter
from config import settings

_ER_QUERY_TIMEOUT = 3024
# 2003 não conecta, 2006 servidor sumiu, 2013 conexão perdida na query, 2055 idem (lost connection),
# 1040 too many connections, 1053 shutdown em andamento
_TRANSIENT_ERROR_CODES = {2003, 2006, 2013, 2055, 1040, 1053}


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
            # aiomysql não tem timeout por query (só connect_timeout, que vale para o
            # handshake). max_execution_time (ms) faz o servidor abortar SELECTs lentos
            # — RNF2/§8.1, equivalente ao command_timeout do asyncpg. Exige MySQL >= 5.7.8;
            # MariaDB usa max_statement_time e recusaria esta variável.
            init_command=f"SET SESSION max_execution_time={settings.query_timeout_seconds * 1000}",
        )

    async def disconnect(self) -> None:
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()

    async def execute_query(self, query: str, params: dict | None = None, scalar: bool = False):
        """Executa query parametrizada com placeholders %(name)s (MySQL named params).

        scalar=True retorna um valor escalar (ex: COUNT(*)); scalar=False
        (padrão) retorna list[dict], uma linha por dict.
        """
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # aiomysql usa %(name)s placeholders e espera um dict como parâmetro
                await cursor.execute(query, params or {})
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

    @staticmethod
    def _error_code(exc: Exception) -> int | None:
        """Código numérico do MySQL (args[0] de um OperationalError), ou None."""
        if isinstance(exc, aiomysql.OperationalError) and exc.args and isinstance(exc.args[0], int):
            return exc.args[0]
        return None

    def is_timeout_error(self, exc: Exception) -> bool:
        # 3024 = ER_QUERY_TIMEOUT (max_execution_time do init_command estourou)
        return self._error_code(exc) == _ER_QUERY_TIMEOUT

    def is_transient_error(self, exc: Exception) -> bool:
        if isinstance(exc, ConnectionError):
            return True
        code = self._error_code(exc)
        if code not in _TRANSIENT_ERROR_CODES:
            return False
        # 2003 também cobre o estouro do connect_timeout ("timed out") — não repetir (decisão 8)
        return "timed out" not in str(exc).lower()

    def translate_params(self, sql: str, param_names: list[str]) -> str:
        """Traduz placeholders nomeados (:param) para MySQL (%(param)s).

        aiomysql suporta named placeholders %(name)s, permitindo que um mesmo
        parâmetro seja usado múltiplas vezes na query (como PostgreSQL com $1, $1, etc).

        Exemplo:
            input:  "SELECT * FROM t WHERE x = :x AND (y = :y OR z = :y)", ["x", "y"]
            output: "SELECT * FROM t WHERE x = %(x)s AND (y = %(y)s OR z = %(y)s)"
        """
        translated = sql
        for name in param_names:
            translated = re.sub(rf":{re.escape(name)}\b", f"%({name})s", translated)
        return translated
