"""Acesso a data_sources no Config DB — ARQUITETURA.md §2.2/§4.1,
F4_EXECUTION_ENGINE.md §4.4."""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from adapters.postgresql import PostgreSQLAdapter
from repositories.sql_helpers import like_pattern

_SUMMARY = (
    "ds.id, ds.name, ds.type, ds.is_active, ds.created_by, ds.created_at, ds.updated_at, "
    "(SELECT COUNT(*) FROM analyses a WHERE a.data_source_id = ds.id) AS analyses_count"
)
_FILTERS = (
    "WHERE ($1::text IS NULL OR ds.name ILIKE $1 ESCAPE '\\') "
    "AND ($2::text IS NULL OR ds.type = $2) "
    "AND ($3::bool IS NULL OR ds.is_active = $3)"
)


@dataclass
class DataSource:
    id: UUID
    name: str
    type: str
    connection_config: dict[str, Any]
    is_active: bool


class DataSourceRepository:
    def __init__(self, config_db_adapter: PostgreSQLAdapter) -> None:
        self._db = config_db_adapter

    async def get_by_id(self, data_source_id: UUID, db=None) -> DataSource | None:
        rows = await (db or self._db).execute_query(
            "SELECT id, name, type, connection_config, is_active "
            "FROM data_sources WHERE id = $1",
            {"id": data_source_id},
        )
        if not rows:
            return None

        row = rows[0]
        connection_config = row["connection_config"]
        if isinstance(connection_config, str):
            connection_config = json.loads(connection_config)

        return DataSource(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            connection_config=connection_config,
            is_active=row["is_active"],
        )

    # ---- F24: administração (aceitam `db` opcional: adapter ou Transaction) ----

    async def list_page(
        self, q: str | None, type_: str | None, is_active: bool | None, limit: int, offset: int
    ) -> tuple[list[dict], int]:
        filters = {"q": like_pattern(q), "type": type_, "is_active": is_active}
        total = await self._db.execute_query(
            f"SELECT COUNT(*) FROM data_sources ds {_FILTERS}", filters, scalar=True
        )
        rows = await self._db.execute_query(
            f"SELECT {_SUMMARY} FROM data_sources ds {_FILTERS} "
            "ORDER BY ds.name, ds.id LIMIT $4 OFFSET $5",
            {**filters, "limit": limit, "offset": offset},
        )
        return rows, total

    async def get_summary(self, data_source_id: UUID, db=None) -> dict | None:
        rows = await (db or self._db).execute_query(
            f"SELECT {_SUMMARY} FROM data_sources ds WHERE ds.id = $1", {"id": data_source_id}
        )
        return rows[0] if rows else None

    async def get_analyses(self, data_source_id: UUID, db=None) -> list[dict]:
        return await (db or self._db).execute_query(
            "SELECT id, name, is_active FROM analyses WHERE data_source_id = $1 ORDER BY name, id",
            {"data_source_id": data_source_id},
        )

    async def create(
        self, name: str, type_: str, connection_config: dict, is_active: bool,
        created_by: str | None, db=None,
    ) -> UUID:
        return await (db or self._db).execute_query(
            "INSERT INTO data_sources (name, type, connection_config, is_active, created_by) "
            "VALUES ($1, $2, $3::jsonb, $4, $5) RETURNING id",
            {
                "name": name, "type": type_, "connection_config": json.dumps(connection_config),
                "is_active": is_active, "created_by": created_by,
            },
            scalar=True,
        )

    async def update(self, data_source_id: UUID, fields: dict, db=None) -> bool:
        """`fields`: name, is_active, connection_config (dict → JSONB). `updated_at` sempre atualizado."""
        values = {k: (json.dumps(v) if k == "connection_config" else v) for k, v in fields.items()}
        parts = [
            f"{col} = ${i}::jsonb" if col == "connection_config" else f"{col} = ${i}"
            for i, col in enumerate(values, start=2)
        ]
        rows = await (db or self._db).execute_query(
            f"UPDATE data_sources SET {', '.join(parts + ['updated_at = NOW()'])} "
            "WHERE id = $1 RETURNING id",
            {"id": data_source_id, **values},
        )
        return bool(rows)

    async def delete(self, data_source_id: UUID, db=None) -> bool:
        rows = await (db or self._db).execute_query(
            "DELETE FROM data_sources WHERE id = $1 RETURNING id", {"id": data_source_id}
        )
        return bool(rows)

    async def touch_analyses(self, data_source_id: UUID, db=None) -> None:
        """updated_at das analyses do data source: o cache não conhece o data source (F24 decisão 10)."""
        await (db or self._db).execute_query(
            "UPDATE analyses SET updated_at = NOW() WHERE data_source_id = $1 RETURNING id",
            {"data_source_id": data_source_id},
        )
