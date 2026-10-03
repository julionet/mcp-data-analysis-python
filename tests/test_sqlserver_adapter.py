"""Testes unitários do F11 — SQL Server Adapter — ver F11_SQLSERVER_ADAPTER.md §6.1.

O driver ``aioodbc`` é mockado: nenhum teste aqui exige SQL Server ou driver ODBC.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.sqlserver import SQLServerAdapter
from config import settings

CONFIG = {
    "host": "localhost",
    "port": 1433,
    "user": "readonly",
    "password": "senha_decifrada",
    "database": "vendas",
}


def make_pool(cursor: MagicMock) -> MagicMock:
    """Pool falso: pool.acquire() → conn; conn.cursor() → cursor (ambos async ctx managers)."""
    conn = MagicMock()
    conn.cursor.return_value.__aenter__.return_value = cursor
    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool


def make_cursor(description=None, rows=None, one=None) -> MagicMock:
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows or [])
    cursor.fetchone = AsyncMock(return_value=one)
    cursor.description = description
    return cursor


def adapter_with(cursor: MagicMock) -> SQLServerAdapter:
    adapter = SQLServerAdapter(CONFIG)
    adapter._pool = make_pool(cursor)
    return adapter


class TestSQLServerAdapter:
    # translate_params
    def test_translate_params_single(self):
        result = SQLServerAdapter({}).translate_params("SELECT * FROM t WHERE x = :x", ["x"])
        assert result == "SELECT * FROM t WHERE x = @x"

    def test_translate_params_multiple(self):
        sql = "SELECT * FROM t WHERE x = :x AND y = :y"
        result = SQLServerAdapter({}).translate_params(sql, ["x", "y"])
        assert result == "SELECT * FROM t WHERE x = @x AND y = @y"

    def test_translate_params_word_boundary(self):
        sql = "SELECT :data_inicial, :data FROM t WHERE c = :data"
        result = SQLServerAdapter({}).translate_params(sql, ["data"])
        assert result.count("@data") == 2
        assert ":data_inicial" in result

    def test_translate_params_empty_list(self):
        sql = "SELECT * FROM t"
        assert SQLServerAdapter({}).translate_params(sql, []) == sql

    def test_translate_params_reuse_same_param(self):
        sql = "WHERE (:termo IS NULL OR descricao LIKE :termo)"
        result = SQLServerAdapter({}).translate_params(sql, ["termo"])
        assert result == "WHERE (@termo IS NULL OR descricao LIKE @termo)"

    # _to_positional (@nome → ?)
    def test_to_positional_occurrence_order(self):
        sql, values = SQLServerAdapter._to_positional(
            "WHERE y = @y AND x = @x", {"x": 1, "y": 2}
        )
        assert sql == "WHERE y = ? AND x = ?"
        assert values == [2, 1]

    def test_to_positional_repeated_param(self):
        sql, values = SQLServerAdapter._to_positional(
            "WHERE (@termo IS NULL OR descricao LIKE @termo)", {"termo": "abc"}
        )
        assert sql == "WHERE (? IS NULL OR descricao LIKE ?)"
        assert values == ["abc", "abc"]

    def test_to_positional_ignores_system_variables(self):
        sql, values = SQLServerAdapter._to_positional(
            "SELECT @@ROWCOUNT, @local, @x", {"x": 1}
        )
        assert sql == "SELECT @@ROWCOUNT, @local, ?"
        assert values == [1]

    def test_to_positional_no_params(self):
        sql, values = SQLServerAdapter._to_positional("SELECT 1", None)
        assert (sql, values) == ("SELECT 1", [])

    # connection string
    def test_connection_string_defaults(self):
        config = {k: v for k, v in CONFIG.items() if k != "port"}
        conn_str = SQLServerAdapter(config)._build_connection_string()
        assert "DRIVER={ODBC Driver 18 for SQL Server};" in conn_str
        assert "SERVER=localhost,1433;" in conn_str
        assert conn_str.endswith("Encrypt=yes;TrustServerCertificate=yes")

    def test_connection_string_custom_driver(self):
        config = {**CONFIG, "driver": "ODBC Driver 17 for SQL Server"}
        conn_str = SQLServerAdapter(config)._build_connection_string()
        assert "DRIVER={ODBC Driver 17 for SQL Server};" in conn_str

    @pytest.mark.parametrize(
        "sslmode, expected",
        [
            ("disable", "Encrypt=no"),
            ("prefer", "Encrypt=yes;TrustServerCertificate=yes"),
            ("verify-full", "Encrypt=yes;TrustServerCertificate=no"),
        ],
    )
    def test_connection_string_sslmode_mapping(self, sslmode, expected):
        conn_str = SQLServerAdapter({**CONFIG, "sslmode": sslmode})._build_connection_string()
        assert conn_str.endswith(";" + expected)

    def test_connection_string_invalid_sslmode(self):
        with pytest.raises(ValueError, match="sslmode 'require' não suportado para sqlserver"):
            SQLServerAdapter({**CONFIG, "sslmode": "require"})._build_connection_string()

    def test_connection_string_escapes_password(self):
        conn_str = SQLServerAdapter({**CONFIG, "password": "a;b}c"})._build_connection_string()
        assert "PWD={a;b}}c};" in conn_str

    # execução
    @pytest.mark.asyncio
    async def test_connect_passes_autocommit_timeout_and_pool_size(self):
        with patch("adapters.sqlserver.aioodbc.create_pool", new=AsyncMock()) as create_pool:
            adapter = SQLServerAdapter(CONFIG)
            await adapter.connect()

        kwargs = create_pool.await_args.kwargs
        assert kwargs["minsize"] == 1
        assert kwargs["maxsize"] == 10
        assert kwargs["autocommit"] is True
        assert kwargs["timeout"] == settings.query_timeout_seconds
        assert kwargs["dsn"] == adapter._build_connection_string()
        assert adapter._pool is create_pool.return_value

    @pytest.mark.asyncio
    async def test_connect_invalid_sslmode_fails_before_opening_pool(self):
        with patch("adapters.sqlserver.aioodbc.create_pool", new=AsyncMock()) as create_pool:
            with pytest.raises(ValueError):
                await SQLServerAdapter({**CONFIG, "sslmode": "require"}).connect()

        create_pool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_query_returns_list_of_dicts(self):
        cursor = make_cursor(description=[("a",), ("b",)], rows=[(1, "x"), (2, "y")])
        result = await adapter_with(cursor).execute_query(
            "SELECT a, b FROM t WHERE a > @a", {"a": 0}
        )

        assert result == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        cursor.execute.assert_awaited_once_with("SELECT a, b FROM t WHERE a > ?", 0)

    @pytest.mark.asyncio
    async def test_execute_query_empty_returns_empty_list(self):
        cursor = make_cursor(description=[("a",)], rows=[])
        assert await adapter_with(cursor).execute_query("SELECT a FROM t") == []

    @pytest.mark.asyncio
    async def test_execute_query_scalar(self):
        cursor = make_cursor(one=(42,))
        result = await adapter_with(cursor).execute_query("SELECT COUNT(*) FROM t", scalar=True)
        assert result == 42

    @pytest.mark.asyncio
    async def test_execute_query_scalar_empty_returns_none(self):
        cursor = make_cursor(one=None)
        assert await adapter_with(cursor).execute_query("SELECT 1 WHERE 1=0", scalar=True) is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "message",
        [
            "[42000] ORDER BY clause is invalid in views, inline functions, "
            "derived tables, subqueries",
            "[42000] (1033) ORDER BY ...",
            "[42000] (8155) No column name was specified for column 1",
            "[42000] (8156) The column 'a' was specified multiple times",
        ],
    )
    async def test_execute_query_translates_native_error_1033(self, message):
        cursor = make_cursor()
        native = Exception(message)
        cursor.execute.side_effect = native

        with pytest.raises(RuntimeError, match="subconjunto comum") as exc_info:
            await adapter_with(cursor).execute_query("SELECT COUNT(*) FROM (SELECT 1) AS sub")

        assert exc_info.value.__cause__ is native

    @pytest.mark.asyncio
    async def test_execute_query_other_errors_are_not_translated(self):
        cursor = make_cursor()
        cursor.execute.side_effect = Exception("(156) Incorrect syntax near the keyword 'WITH'")

        with pytest.raises(Exception, match=r"\(156\)") as exc_info:
            await adapter_with(cursor).execute_query("WITH c AS (SELECT 1) SELECT * FROM c")

        assert not isinstance(exc_info.value, RuntimeError)

    @pytest.mark.asyncio
    async def test_execute_dml(self):
        cursor = make_cursor()
        await adapter_with(cursor).execute("UPDATE t SET a = ? WHERE b = ?", 1, 2)
        cursor.execute.assert_awaited_once_with("UPDATE t SET a = ? WHERE b = ?", 1, 2)

    @pytest.mark.asyncio
    async def test_test_connection_success_and_failure(self):
        ok = adapter_with(make_cursor(description=[("",)], rows=[(1,)]))
        assert await ok.test_connection() is True

        cursor = make_cursor()
        cursor.execute.side_effect = Exception("boom")
        assert await adapter_with(cursor).test_connection() is False

    @pytest.mark.asyncio
    async def test_test_connection_without_connect_returns_false(self):
        assert await SQLServerAdapter(CONFIG).test_connection() is False

    @pytest.mark.asyncio
    async def test_disconnect_closes_pool(self):
        adapter = SQLServerAdapter(CONFIG)
        pool = MagicMock()
        pool.wait_closed = AsyncMock()
        adapter._pool = pool

        await adapter.disconnect()

        pool.close.assert_called_once_with()
        pool.wait_closed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_without_pool_is_noop(self):
        await SQLServerAdapter(CONFIG).disconnect()
