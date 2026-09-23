"""Testes unitários da F2 — ver F2_POSTGRESQL_ADAPTER.md §6.1."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.postgresql import PostgreSQLAdapter

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
        )
        assert adapter._pool is fake_pool

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
