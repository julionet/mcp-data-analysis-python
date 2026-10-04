"""Testes unitários da F14 — classificação de erros por adapter (spec §4.3).

Usa as exceções reais dos drivers (asyncpg, aiomysql, pyodbc, oracledb) para cobrir
o contrato `is_timeout_error` / `is_transient_error`. Oracle: o `args[0]` do
oracledb.Error é um objeto com `full_code` (conferido no driver 26.x); aqui ele é
simulado, já que não há instância Oracle.
"""

from types import SimpleNamespace

import aiomysql
import asyncpg
import oracledb
import pyodbc
import pytest

from adapters.base import DatabaseAdapter
from adapters.mysql import MySQLAdapter
from adapters.oracle import OracleAdapter
from adapters.postgresql import PostgreSQLAdapter
from adapters.sqlserver import SQLServerAdapter


def _ora(full_code: str) -> oracledb.DatabaseError:
    return oracledb.DatabaseError(SimpleNamespace(full_code=full_code, message=full_code))


class _BareAdapter(DatabaseAdapter):
    async def connect(self): ...
    async def disconnect(self): ...
    async def execute_query(self, query, params=None, scalar=False): ...
    async def execute(self, query, *args): ...
    async def test_connection(self): ...
    def translate_params(self, sql, param_names): ...


def test_base_adapter_never_classifies():
    adapter = _BareAdapter({})
    assert adapter.is_timeout_error(TimeoutError()) is False
    assert adapter.is_transient_error(ConnectionRefusedError()) is False


# (adapter, exceção, é_timeout, é_transitório)
CASES = [
    # --- PostgreSQL
    (PostgreSQLAdapter, asyncpg.QueryCanceledError(), True, False),
    (PostgreSQLAdapter, TimeoutError(), True, False),
    (PostgreSQLAdapter, asyncpg.ConnectionDoesNotExistError(), False, True),
    (PostgreSQLAdapter, asyncpg.CannotConnectNowError(), False, True),
    (PostgreSQLAdapter, asyncpg.TooManyConnectionsError(), False, True),
    (PostgreSQLAdapter, ConnectionRefusedError(), False, True),
    (PostgreSQLAdapter, ConnectionResetError(), False, True),
    (PostgreSQLAdapter, asyncpg.InvalidPasswordError(), False, False),
    (PostgreSQLAdapter, asyncpg.PostgresSyntaxError(), False, False),
    (PostgreSQLAdapter, ValueError("x"), False, False),
    # --- MySQL (args = (código, mensagem))
    (MySQLAdapter, aiomysql.OperationalError(3024, "Query execution was interrupted, maximum statement execution time exceeded"), True, False),
    (MySQLAdapter, aiomysql.OperationalError(2003, "Can't connect to MySQL server on 'h' ([Errno 111] Connection refused)"), False, True),
    (MySQLAdapter, aiomysql.OperationalError(2003, "Can't connect to MySQL server on 'h' (timed out)"), False, False),
    (MySQLAdapter, aiomysql.OperationalError(2006, "MySQL server has gone away"), False, True),
    (MySQLAdapter, aiomysql.OperationalError(2013, "Lost connection to MySQL server during query"), False, True),
    (MySQLAdapter, aiomysql.OperationalError(1040, "Too many connections"), False, True),
    (MySQLAdapter, aiomysql.OperationalError(1045, "Access denied for user"), False, False),
    (MySQLAdapter, aiomysql.ProgrammingError(1064, "You have an error in your SQL syntax"), False, False),
    (MySQLAdapter, ConnectionResetError(), False, True),
    # --- SQL Server (args = (SQLSTATE, mensagem))
    (SQLServerAdapter, pyodbc.OperationalError("HYT00", "[HYT00] [Microsoft][ODBC Driver 18 for SQL Server]Query timeout expired (0) (SQLExecDirectW)"), True, False),
    (SQLServerAdapter, pyodbc.OperationalError("HYT00", "[HYT00] [Microsoft][ODBC Driver 18 for SQL Server]Login timeout expired (0) (SQLDriverConnect)"), False, False),
    (SQLServerAdapter, pyodbc.OperationalError("HYT01", "[HYT01] Connection timeout expired"), False, False),
    (SQLServerAdapter, pyodbc.OperationalError("08S01", "[08S01] Communication link failure"), False, True),
    (SQLServerAdapter, pyodbc.OperationalError("08001", "[08001] Client unable to establish connection"), False, True),
    (SQLServerAdapter, pyodbc.ProgrammingError("42000", "[42000] Incorrect syntax near 'x'"), False, False),
    (SQLServerAdapter, pyodbc.InterfaceError("28000", "[28000] Login failed for user"), False, False),
    (SQLServerAdapter, ConnectionRefusedError(), False, True),
    # --- Oracle (args[0].full_code)
    (OracleAdapter, _ora("DPY-4024"), True, False),
    (OracleAdapter, _ora("ORA-03156"), True, False),
    (OracleAdapter, _ora("DPY-4011"), False, True),
    (OracleAdapter, _ora("ORA-03113"), False, True),
    (OracleAdapter, _ora("ORA-12541"), False, True),
    (OracleAdapter, _ora("DPY-6005"), False, False),
    (OracleAdapter, _ora("ORA-00942"), False, False),
    (OracleAdapter, RuntimeError("SQL fora do subconjunto comum"), False, False),
    (OracleAdapter, ConnectionRefusedError(), False, True),
]


@pytest.mark.parametrize(
    ("adapter_cls", "exc", "is_timeout", "is_transient"),
    CASES,
    ids=[f"{c[0].__name__}-{type(c[1]).__name__}-{i}" for i, c in enumerate(CASES)],
)
def test_error_classification(adapter_cls, exc, is_timeout, is_transient):
    adapter = adapter_cls({})
    assert adapter.is_timeout_error(exc) is is_timeout
    assert adapter.is_transient_error(exc) is is_transient


@pytest.mark.parametrize(("adapter_cls", "exc", "is_timeout", "is_transient"), CASES)
def test_timeout_and_transient_are_mutually_exclusive(adapter_cls, exc, is_timeout, is_transient):
    # Garante a decisão 8: um timeout nunca recebe retry automático.
    assert not (is_timeout and is_transient)
