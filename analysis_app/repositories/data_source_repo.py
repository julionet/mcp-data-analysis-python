"""Acesso a data_sources no Config DB — ARQUITETURA.md §2.2/§4.1,
F4_EXECUTION_ENGINE.md §4.4."""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from adapters.postgresql import PostgreSQLAdapter


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

    async def get_by_id(self, data_source_id: UUID) -> DataSource | None:
        rows = await self._db.execute_query(
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
