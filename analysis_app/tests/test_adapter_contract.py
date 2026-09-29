"""Contrato agnóstico dos adapters — F11_SQLSERVER_ADAPTER.md §6.1.

Os mesmos cenários de parâmetros rodam contra PostgreSQL, MySQL e SQL Server
(drivers mockados). Todo novo adapter deve entrar na fixture ``adapter_case``.

Contrato implícito do PostgreSQL: ``$n`` refere-se à n-ésima chave de ``params``,
ou seja, o caller (``analysis_service``, que monta ``ordered_values``) DEVE passar
``params`` na ordem de ``param_names``. Os cenários abaixo respeitam isso; se alguém
mudar a montagem de ``ordered_values``, estes testes são o alarme.
"""

import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.factory import AdapterFactory
from adapters.mysql import MySQLAdapter
from adapters.postgresql import PostgreSQLAdapter
from adapters.sqlserver import SQLServerAdapter

# params sempre na ordem de param_names (contrato implícito do PostgreSQL)
CENARIOS = [
    ("SELECT * FROM t WHERE x = :x", ["x"], {"x": 1}),
    (
        "SELECT * FROM t WHERE x = :x AND y = :y AND z = :z",
        ["x", "y", "z"],
        {"x": 1, "y": "dois", "z": None},
    ),
    ("SELECT * FROM t WHERE y = :y AND x = :x", ["x", "y"], {"x": 1, "y": 2}),
    ("SELECT * FROM t WHERE (:t IS NULL OR d LIKE :t)", ["t"], {"t": "abc"}),
    (
        "SELECT * FROM t WHERE a = :data AND b = :data_inicial",
        ["data", "data_inicial"],
        {"data": "d", "data_inicial": "di"},
    ),
]

_ADAPTERS = {
    "postgresql": PostgreSQLAdapter,
    "mysql": MySQLAdapter,
    "sqlserver": SQLServerAdapter,
}


class AdapterCase:
    """Adapter + driver mockado + helper de resolução de placeholders."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.adapter = _ADAPTERS[kind]({})

    def translated(self, sql: str, param_names: list[str]) -> str:
        return self.adapter.translate_params(sql, param_names)

    def bound_values(self, sql: str, param_names: list[str], params: dict) -> list:
        """Valores que o driver receberia em cada placeholder, na ordem do SQL."""
        translated = self.translated(sql, param_names)
        if self.kind == "postgresql":
            values = list(params.values())  # $n → n-ésima chave (ver docstring do módulo)
            return [values[int(n) - 1] for n in re.findall(r"\$(\d+)", translated)]
        if self.kind == "mysql":
            return [params[name] for name in re.findall(r"%\((\w+)\)s", translated)]
        _, values = SQLServerAdapter._to_positional(translated, params)
        return values

    def install_driver(self, rows: list[dict]) -> None:
        """Mocka o pool do adapter para devolver ``rows`` (list[dict])."""
        pool, conn = MagicMock(), MagicMock()
        pool.acquire.return_value.__aenter__.return_value = conn
        first = next(iter(rows[0].values())) if rows else None
        if self.kind == "postgresql":
            conn.fetch = AsyncMock(return_value=rows)
            conn.fetchval = AsyncMock(return_value=first)
        else:
            cursor = MagicMock()
            cursor.execute = AsyncMock()
            if self.kind == "mysql":
                cursor.fetchall = AsyncMock(return_value=rows)
                cursor.fetchone = AsyncMock(return_value=rows[0] if rows else None)
            else:
                cursor.description = [(k,) for k in rows[0]]
                cursor.fetchall = AsyncMock(return_value=[tuple(r.values()) for r in rows])
                cursor.fetchone = AsyncMock(return_value=tuple(rows[0].values()))
            conn.cursor.return_value.__aenter__.return_value = cursor
        self.adapter._pool = pool


@pytest.fixture(params=list(_ADAPTERS))
def adapter_case(request) -> AdapterCase:
    return AdapterCase(request.param)


def _expected(sql: str, param_names: list[str], params: dict) -> list:
    return [params[n] for n in re.findall(r":(\w+)", sql) if n in param_names]


class TestAdapterContract:
    @pytest.mark.parametrize("sql, param_names, params", CENARIOS)
    def test_each_value_lands_on_its_placeholder(self, adapter_case, sql, param_names, params):
        assert adapter_case.bound_values(sql, param_names, params) == _expected(
            sql, param_names, params
        )

    def test_unknown_placeholder_is_left_untouched(self, adapter_case):
        sql = "SELECT * FROM t WHERE x = :x AND y = :desconhecido"
        translated = adapter_case.translated(sql, ["x"])

        assert ":desconhecido" in translated
        assert ":x" not in translated
        assert adapter_case.bound_values(sql, ["x"], {"x": 1}) == [1]

    @pytest.mark.asyncio
    async def test_execute_query_returns_list_of_dicts(self, adapter_case):
        rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        adapter_case.install_driver(rows)

        assert await adapter_case.adapter.execute_query("SELECT a, b FROM t") == rows

    @pytest.mark.asyncio
    async def test_execute_query_scalar_returns_first_value(self, adapter_case):
        adapter_case.install_driver([{"total": 7}])

        result = await adapter_case.adapter.execute_query(
            "SELECT COUNT(*) AS total FROM t", scalar=True
        )

        assert result == 7

    def test_factory_creates_each_adapter_type(self):
        for kind, cls in _ADAPTERS.items():
            assert isinstance(AdapterFactory.create_adapter(kind, {}), cls)
