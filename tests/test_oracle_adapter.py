"""Testes unitários do F9 — Oracle Adapter — ver F9_ORACLE_ADAPTER.md §6.1.

O driver ``oracledb`` é mockado: nenhum teste aqui exige uma instância Oracle.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.oracle import OracleAdapter
from config import settings

CONFIG = {
    "host": "192.168.1.40",
    "port": 1521,
    "service_name": "ORCLPDB1",
    "user": "readonly",
    "password": "senha_decifrada",
}


def make_pool(cursor: MagicMock) -> tuple[MagicMock, MagicMock]:
    """Pool falso: pool.acquire() → conn; conn.cursor() → cursor (ambos async ctx managers)."""
    conn = MagicMock()
    conn.commit = AsyncMock()
    conn.cursor.return_value.__aenter__.return_value = cursor
    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool, conn


def make_cursor(description=None, rows=None, one=None) -> MagicMock:
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows or [])
    cursor.fetchone = AsyncMock(return_value=one)
    cursor.description = description
    return cursor


def adapter_with(cursor: MagicMock, config: dict = CONFIG) -> tuple[OracleAdapter, MagicMock]:
    adapter = OracleAdapter(config)
    adapter._pool, conn = make_pool(cursor)
    return adapter, conn


class TestOracleAdapter:
    # translate_params
    def test_translate_params_single(self):
        result = OracleAdapter({}).translate_params("SELECT * FROM t WHERE x = :x", ["x"])
        assert result == "SELECT * FROM t WHERE x = :p1"

    def test_translate_params_multiple(self):
        sql = "SELECT * FROM t WHERE x = :x AND y = :y AND z = :z"
        result = OracleAdapter({}).translate_params(sql, ["x", "y", "z"])
        assert result == "SELECT * FROM t WHERE x = :p1 AND y = :p2 AND z = :p3"

    def test_translate_params_follows_param_names_index(self):
        sql = "SELECT * FROM t WHERE y = :y AND x = :x"
        result = OracleAdapter({}).translate_params(sql, ["x", "y"])
        assert result == "SELECT * FROM t WHERE y = :p2 AND x = :p1"

    def test_translate_params_word_boundary(self):
        sql = "SELECT * FROM t WHERE a = :data AND b = :data_inicial"
        result = OracleAdapter({}).translate_params(sql, ["data", "data_inicial"])
        assert result == "SELECT * FROM t WHERE a = :p1 AND b = :p2"

    def test_translate_params_reserved_word_names(self):
        sql = "SELECT * FROM t WHERE d = :date AND l = :level"
        result = OracleAdapter({}).translate_params(sql, ["date", "level"])
        assert result == "SELECT * FROM t WHERE d = :p1 AND l = :p2"

    def test_translate_params_empty_list(self):
        sql = "SELECT * FROM t WHERE x = :x"
        assert OracleAdapter({}).translate_params(sql, []) == sql

    def test_translate_params_reuse_same_param(self):
        sql = "SELECT * FROM t WHERE (:t IS NULL OR d LIKE :t)"
        result = OracleAdapter({}).translate_params(sql, ["t"])
        assert result == "SELECT * FROM t WHERE (:p1 IS NULL OR d LIKE :p1)"

    def test_translate_params_name_equal_to_generated_placeholder(self):
        """Passo único: parâmetro chamado 'p1' não corrompe o :p1 já gerado."""
        result = OracleAdapter({}).translate_params("SELECT :a, :p1 FROM t", ["a", "p1"])
        assert result == "SELECT :p1, :p2 FROM t"

    # DSN
    def test_dsn_from_service_name(self):
        dsn = OracleAdapter(CONFIG)._build_dsn()
        assert "(SERVICE_NAME=ORCLPDB1)" in dsn and "(HOST=192.168.1.40)" in dsn

    def test_dsn_from_sid(self):
        config = {"host": "h", "port": 1521, "sid": "ORCL", "user": "u", "password": "p"}
        dsn = OracleAdapter(config)._build_dsn()
        assert "(SID=ORCL)" in dsn and "SERVICE_NAME" not in dsn

    def test_dsn_default_port_1521(self):
        dsn = OracleAdapter({"host": "h", "service_name": "S"})._build_dsn()
        assert "(PORT=1521)" in dsn

    def test_dsn_both_service_name_and_sid_raises(self):
        with pytest.raises(ValueError, match="service_name"):
            OracleAdapter({"host": "h", "service_name": "S", "sid": "X"})._build_dsn()

    def test_dsn_neither_service_name_nor_sid_raises(self):
        with pytest.raises(ValueError, match="service_name"):
            OracleAdapter({"host": "h"})._build_dsn()

    # connect / disconnect
    @pytest.mark.asyncio
    async def test_connect_pool_args(self):
        pool, _ = make_pool(make_cursor())
        with patch("adapters.oracle.oracledb.create_pool_async", return_value=pool) as create_pool:
            adapter = OracleAdapter(CONFIG)
            await adapter.connect()

        kwargs = create_pool.call_args.kwargs
        assert kwargs["user"] == "readonly" and kwargs["password"] == "senha_decifrada"
        assert kwargs["min"] == 1 and kwargs["max"] == 10
        assert kwargs["tcp_connect_timeout"] == settings.query_timeout_seconds
        assert "(SERVICE_NAME=ORCLPDB1)" in kwargs["dsn"]
        assert adapter._pool is pool

    @pytest.mark.asyncio
    async def test_connect_invalid_config_does_not_open_pool(self):
        with patch("adapters.oracle.oracledb.create_pool_async") as create_pool:
            with pytest.raises(ValueError):
                await OracleAdapter({"host": "h"}).connect()
        create_pool.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_failure_closes_pool_and_raises(self):
        pool = MagicMock()
        pool.acquire.return_value.__aenter__.side_effect = RuntimeError("ORA-01017")
        pool.close = AsyncMock()
        adapter = OracleAdapter(CONFIG)
        with patch("adapters.oracle.oracledb.create_pool_async", return_value=pool):
            with pytest.raises(RuntimeError, match="ORA-01017"):
                await adapter.connect()

        pool.close.assert_awaited_once_with(force=True)
        assert adapter._pool is None

    @pytest.mark.asyncio
    async def test_disconnect_closes_pool(self):
        adapter = OracleAdapter(CONFIG)
        adapter._pool = MagicMock()
        adapter._pool.close = AsyncMock()

        await adapter.disconnect()

        adapter._pool.close.assert_awaited_once()

    # execute_query
    @pytest.mark.asyncio
    async def test_execute_query_binds_by_index(self):
        cursor = make_cursor(description=[("A",)], rows=[])
        adapter, _ = adapter_with(cursor)

        await adapter.execute_query("SELECT a FROM t WHERE x = :p1 AND y = :p2", {"x": 1, "y": "b"})

        assert cursor.execute.await_args.args[1] == {"p1": 1, "p2": "b"}

    @pytest.mark.asyncio
    async def test_execute_query_lowercases_keys(self):
        cursor = make_cursor(description=[("NOME",), ("Total",)], rows=[("a", 1), ("b", 2)])
        adapter, _ = adapter_with(cursor)

        result = await adapter.execute_query("SELECT NOME, Total FROM t")

        assert result == [{"nome": "a", "total": 1}, {"nome": "b", "total": 2}]

    @pytest.mark.asyncio
    async def test_execute_query_passes_fetch_lobs_false_and_decimals_true(self):
        cursor = make_cursor(description=[("V",)], rows=[(Decimal("1.5"),)])
        adapter, _ = adapter_with(cursor)

        await adapter.execute_query("SELECT v FROM t")

        kwargs = cursor.execute.await_args.kwargs
        assert kwargs == {"fetch_lobs": False, "fetch_decimals": True}

    @pytest.mark.asyncio
    async def test_execute_query_sets_call_timeout_ms(self):
        adapter, conn = adapter_with(make_cursor(description=[("V",)]))

        await adapter.execute_query("SELECT v FROM t")

        assert conn.call_timeout == settings.query_timeout_seconds * 1000

    @pytest.mark.asyncio
    async def test_execute_query_scalar(self):
        adapter, _ = adapter_with(make_cursor(one=(7,)))

        assert await adapter.execute_query("SELECT COUNT(*) FROM t", scalar=True) == 7

    @pytest.mark.asyncio
    async def test_execute_query_scalar_empty_returns_none(self):
        adapter, _ = adapter_with(make_cursor(one=None))

        assert await adapter.execute_query("SELECT 1 FROM t", scalar=True) is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code", ["ORA-00911", "ORA-00918"])
    async def test_execute_query_translates_restricted_sql_errors(self, code):
        cursor = make_cursor()
        cursor.execute.side_effect = Exception(f"{code}: erro de sintaxe")
        adapter, _ = adapter_with(cursor)

        with pytest.raises(RuntimeError, match="subconjunto comum") as exc_info:
            await adapter.execute_query("SELECT 1 FROM t")

        assert code in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_query_other_errors_propagate_unchanged(self):
        cursor = make_cursor()
        cursor.execute.side_effect = ValueError("ORA-00942: table or view does not exist")
        adapter, _ = adapter_with(cursor)

        with pytest.raises(ValueError, match="ORA-00942"):
            await adapter.execute_query("SELECT 1 FROM t")

    # execute (DML) / test_connection
    @pytest.mark.asyncio
    async def test_execute_dml_commits(self):
        cursor = make_cursor()
        adapter, conn = adapter_with(cursor)

        await adapter.execute("UPDATE t SET a = :1 WHERE id = :2", "x", 5)

        assert cursor.execute.await_args.args == ("UPDATE t SET a = :1 WHERE id = :2", ["x", 5])
        conn.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_test_connection_uses_dual(self):
        cursor = make_cursor(description=[("1",)], rows=[(1,)])
        adapter, _ = adapter_with(cursor)

        assert await adapter.test_connection() is True
        assert cursor.execute.await_args.args[0] == "SELECT 1 FROM DUAL"

    @pytest.mark.asyncio
    async def test_test_connection_false_on_error(self):
        cursor = make_cursor()
        cursor.execute.side_effect = Exception("ORA-12541: no listener")
        adapter, _ = adapter_with(cursor)

        assert await adapter.test_connection() is False
