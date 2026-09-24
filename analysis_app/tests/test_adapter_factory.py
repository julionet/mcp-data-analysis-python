"""Testes unitários da F4 — ver F4_EXECUTION_ENGINE.md §6.1 (TestAdapterFactory)."""

import pytest

from adapters.factory import AdapterFactory
from adapters.postgresql import PostgreSQLAdapter

CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "chronus",
    "password": "senha_decifrada",
    "database": "data_db",
}


class TestAdapterFactory:
    def test_create_adapter_postgresql(self):
        adapter = AdapterFactory.create_adapter("postgresql", CONFIG)

        assert isinstance(adapter, PostgreSQLAdapter)
        assert adapter.config == CONFIG

    def test_create_adapter_unknown_type_raises(self):
        with pytest.raises(ValueError, match="mongodb"):
            AdapterFactory.create_adapter("mongodb", CONFIG)
