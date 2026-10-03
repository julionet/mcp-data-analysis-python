"""Testes unitários da F4 — ver F4_EXECUTION_ENGINE.md §6.1 (TestAdapterFactory)."""

import pytest

from adapters.factory import AdapterFactory
from adapters.postgresql import PostgreSQLAdapter
from adapters.mysql import MySQLAdapter
from adapters.sqlserver import SQLServerAdapter
from adapters.oracle import OracleAdapter

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

    def test_create_adapter_mysql(self):
        mysql_config = {
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "senha",
            "database": "data_db",
        }
        adapter = AdapterFactory.create_adapter("mysql", mysql_config)

        assert isinstance(adapter, MySQLAdapter)
        assert adapter.config == mysql_config

    def test_create_adapter_sqlserver(self):
        sqlserver_config = {
            "host": "localhost",
            "port": 1433,
            "user": "sa",
            "password": "senha",
            "database": "data_db",
        }
        adapter = AdapterFactory.create_adapter("sqlserver", sqlserver_config)

        assert isinstance(adapter, SQLServerAdapter)
        assert adapter.config == sqlserver_config

    def test_create_adapter_oracle(self):
        oracle_config = {
            "host": "localhost",
            "port": 1521,
            "user": "readonly",
            "password": "senha",
            "service_name": "ORCLPDB1",
        }
        adapter = AdapterFactory.create_adapter("oracle", oracle_config)

        assert isinstance(adapter, OracleAdapter)
        assert adapter.config == oracle_config

    def test_create_adapter_unknown_type_raises(self):
        with pytest.raises(ValueError, match="mongodb"):
            AdapterFactory.create_adapter("mongodb", CONFIG)
