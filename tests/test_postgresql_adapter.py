"""Testes unitários da F2 — ver F2_POSTGRESQL_ADAPTER.md §6.1."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.postgresql import PostgreSQLAdapter
from config import settings

CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "test_user",
    "password": "test_password",
    "database": "test_db",
}


class _FakeAcquireContext:
    def __init__(self, conn: MagicMock) -> None:
        self._conn = conn

    async def __aenter__(self) -> MagicMock:
        return self._conn

    async def __aexit__(self, *exc_info) -> None:
        return None


class TestPostgreSQLAdapter:
    @pytest.mark.asyncio
    async def test_connect_success(self):
        adapter = PostgreSQLAdapter(CONFIG)
        fake_pool = MagicMock()

        with patch("adapters.postgresql.asyncpg.create_pool", new=AsyncMock(return_value=fake_pool)) as mock_create_pool:
            await adapter.connect()

        mock_create_pool.assert_awaited_once_with(
            host="localhost",
            port=5432,
            user="test_user",
            password="test_password",
            database="test_db",
            command_timeout=settings.query_timeout_seconds,
            min_size=10,
            max_size=10,
        )
        assert adapter._pool is fake_pool

    @pytest.mark.asyncio
    async def test_pool_respeita_env(self):
        """F15: PG_POOL_MIN/MAX_SIZE alterados chegam ao create_pool."""
        adapter = PostgreSQLAdapter(CONFIG)
        with patch.object(settings, "pg_pool_min_size", 2), patch.object(settings, "pg_pool_max_size", 5):
            with patch("adapters.postgresql.asyncpg.create_pool", new=AsyncMock()) as mock_create_pool:
                await adapter.connect()
        assert mock_create_pool.await_args.kwargs["min_size"] == 2
        assert mock_create_pool.await_args.kwargs["max_size"] == 5

    @pytest.mark.asyncio
    async def test_pool_respeita_connection_config(self):
        """F15: pool_min_size/pool_max_size do connection_config sobrepõem o .env."""
        adapter = PostgreSQLAdapter({**CONFIG, "pool_min_size": 1, "pool_max_size": 3})
        with patch("adapters.postgresql.asyncpg.create_pool", new=AsyncMock()) as mock_create_pool:
            await adapter.connect()
        assert mock_create_pool.await_args.kwargs["min_size"] == 1
        assert mock_create_pool.await_args.kwargs["max_size"] == 3

    @pytest.mark.asyncio
    async def test_execute_query_returns_list_of_dicts(self):
        adapter = PostgreSQLAdapter(CONFIG)
        fake_conn = MagicMock()
        fake_conn.fetch = AsyncMock(return_value=[{"id": 1, "nome": "produto"}])
        fake_pool = MagicMock()
        fake_pool.acquire = MagicMock(return_value=_FakeAcquireContext(fake_conn))
        adapter._pool = fake_pool

        result = await adapter.execute_query("SELECT * FROM produtos WHERE preco > $1", {"preco": 100})

        assert result == [{"id": 1, "nome": "produto"}]
        assert isinstance(result, list)
        assert all(isinstance(row, dict) for row in result)

    @pytest.mark.asyncio
    async def test_execute_query_is_parametrized(self):
        adapter = PostgreSQLAdapter(CONFIG)
        fake_conn = MagicMock()
        fake_conn.fetch = AsyncMock(return_value=[])
        fake_pool = MagicMock()
        fake_pool.acquire = MagicMock(return_value=_FakeAcquireContext(fake_conn))
        adapter._pool = fake_pool

        await adapter.execute_query("SELECT * FROM produtos WHERE preco > $1", {"preco": 100})

        # a query é passada intacta (sem concatenação/f-string) e os valores
        # são enviados separadamente, como argumentos posicionais do asyncpg.
        fake_conn.fetch.assert_awaited_once_with("SELECT * FROM produtos WHERE preco > $1", 100)

    @pytest.mark.asyncio
    async def test_test_connection_false_on_failure(self):
        adapter = PostgreSQLAdapter(CONFIG)
        adapter.execute_query = AsyncMock(side_effect=Exception("connection refused"))

        result = await adapter.test_connection()

        assert result is False


class TestPostgreSQLAdapterScalar:
    """F3_CONTROLE_VOLUME.md §6.1 — parâmetro `scalar` de execute_query."""

    @pytest.mark.asyncio
    async def test_execute_query_scalar_true_returns_int(self):
        adapter = PostgreSQLAdapter(CONFIG)
        fake_conn = MagicMock()
        fake_conn.fetchval = AsyncMock(return_value=300)
        fake_pool = MagicMock()
        fake_pool.acquire = MagicMock(return_value=_FakeAcquireContext(fake_conn))
        adapter._pool = fake_pool

        result = await adapter.execute_query("SELECT COUNT(*) FROM produtos", {}, scalar=True)

        assert result == 300
        fake_conn.fetchval.assert_awaited_once_with("SELECT COUNT(*) FROM produtos")
        fake_conn.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_query_scalar_false_returns_list_dict(self):
        # comportamento atual (F2) não pode regredir
        adapter = PostgreSQLAdapter(CONFIG)
        fake_conn = MagicMock()
        fake_conn.fetch = AsyncMock(return_value=[{"id": 1, "nome": "produto"}])
        fake_pool = MagicMock()
        fake_pool.acquire = MagicMock(return_value=_FakeAcquireContext(fake_conn))
        adapter._pool = fake_pool

        result = await adapter.execute_query("SELECT * FROM produtos")

        assert result == [{"id": 1, "nome": "produto"}]
        assert isinstance(result, list)


class TestPostgresTransactionAndPool:
    """F17 — Transaction, execute(), transaction() e disconnect() sem banco (pool simulado)."""

    @staticmethod
    def _pool():
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[{"a": 1}])
        conn.fetchval = AsyncMock(return_value=7)
        conn.execute = AsyncMock()
        conn.transaction.return_value.__aenter__ = AsyncMock()
        conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        pool.close = AsyncMock()
        return pool, conn

    @pytest.mark.asyncio
    async def test_execute_passes_positional_args(self):
        pool, conn = self._pool()
        adapter = PostgreSQLAdapter({})
        adapter._pool = pool

        await adapter.execute("UPDATE t SET a = $1", 5)

        conn.execute.assert_awaited_once_with("UPDATE t SET a = $1", 5)

    @pytest.mark.asyncio
    async def test_transaction_wraps_connection_with_same_semantics(self):
        pool, conn = self._pool()
        adapter = PostgreSQLAdapter({})
        adapter._pool = pool

        async with adapter.transaction() as tx:
            assert await tx.execute_query("SELECT $1", {"x": 1}) == [{"a": 1}]
            assert await tx.execute_query("SELECT COUNT(*)", scalar=True) == 7
            await tx.execute("DELETE FROM t WHERE id = $1", 3)

        conn.fetch.assert_awaited_once_with("SELECT $1", 1)
        conn.execute.assert_awaited_once_with("DELETE FROM t WHERE id = $1", 3)
        conn.transaction.return_value.__aexit__.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_transaction_propagates_the_exception_from_the_block(self):
        pool, _ = self._pool()
        adapter = PostgreSQLAdapter({})
        adapter._pool = pool

        with pytest.raises(RuntimeError):
            async with adapter.transaction():
                raise RuntimeError("falhou")

    @pytest.mark.asyncio
    async def test_disconnect_closes_pool_and_without_pool_is_noop(self):
        pool, _ = self._pool()
        adapter = PostgreSQLAdapter({})
        adapter._pool = pool
        await adapter.disconnect()
        pool.close.assert_awaited_once()

        adapter._pool = None
        await adapter.disconnect()


class TestPostgresTestConnection:
    @pytest.mark.asyncio
    async def test_true_when_select_works_false_when_it_fails(self):
        adapter = PostgreSQLAdapter({})
        adapter.execute_query = AsyncMock(return_value=[{"?column?": 1}])
        assert await adapter.test_connection() is True

        adapter.execute_query = AsyncMock(side_effect=OSError("down"))
        assert await adapter.test_connection() is False
