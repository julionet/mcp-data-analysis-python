"""Acesso a `users` no Config DB — F12_AUTENTICACAO_PERFIS.md §4.4."""

from dataclasses import dataclass
from uuid import UUID

from adapters.postgresql import PostgreSQLAdapter

_COLUMNS = "id, name, external_id, password_hash, is_blocked"


@dataclass
class User:
    id: UUID
    name: str
    external_id: str | None
    password_hash: str | None
    is_blocked: bool


def _to_user(row: dict) -> User:
    return User(
        id=row["id"],
        name=row["name"],
        external_id=row["external_id"],
        password_hash=row["password_hash"],
        is_blocked=row["is_blocked"],
    )


class UserRepository:
    def __init__(self, config_db_adapter: PostgreSQLAdapter) -> None:
        self._db = config_db_adapter

    async def get_by_id(self, user_id: UUID) -> User | None:
        rows = await self._db.execute_query(
            f"SELECT {_COLUMNS} FROM users WHERE id = $1", {"id": user_id}
        )
        return _to_user(rows[0]) if rows else None

    async def get_by_external_id(self, external_id: str) -> User | None:
        """Recebe o e-mail já normalizado (minúsculas, sem espaços)."""
        rows = await self._db.execute_query(
            f"SELECT {_COLUMNS} FROM users WHERE external_id = $1",
            {"external_id": external_id},
        )
        return _to_user(rows[0]) if rows else None
