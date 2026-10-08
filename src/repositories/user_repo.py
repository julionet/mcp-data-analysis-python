"""Acesso a `users` no Config DB — F12_AUTENTICACAO_PERFIS.md §4.4 e F23 §4.1.

Os métodos administrativos (F23) aceitam um `db` opcional: o adapter (padrão) ou uma
`Transaction` — assim o serviço agrupa várias escritas numa transação só.
"""

from dataclasses import dataclass
from uuid import UUID

from adapters.postgresql import PostgreSQLAdapter
from repositories.sql_helpers import like_pattern, set_clause

_COLUMNS = "id, name, external_id, password_hash, is_blocked, is_admin"
_ADMIN_COLUMNS = (
    "id, name, external_id, is_blocked, is_admin, created_by, created_at, updated_at"
)


@dataclass
class User:
    id: UUID
    name: str
    external_id: str | None
    password_hash: str | None
    is_blocked: bool
    is_admin: bool = False


def _to_user(row: dict) -> User:
    return User(
        id=row["id"],
        name=row["name"],
        external_id=row["external_id"],
        password_hash=row["password_hash"],
        is_blocked=row["is_blocked"],
        is_admin=row["is_admin"],
    )


class UserRepository:
    def __init__(self, config_db_adapter: PostgreSQLAdapter) -> None:
        self._db = config_db_adapter

    async def get_by_id(self, user_id: UUID, db=None) -> User | None:
        rows = await (db or self._db).execute_query(
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

    # ---- F23: administração ----

    @staticmethod
    def _filters() -> str:
        return (
            "WHERE ($1::text IS NULL OR u.name ILIKE $1 ESCAPE '\\' OR u.external_id ILIKE $1 ESCAPE '\\') "
            "AND ($2::bool IS NULL OR u.is_blocked = $2) "
            "AND ($3::uuid IS NULL OR EXISTS ("
            "SELECT 1 FROM user_profiles up WHERE up.user_id = u.id AND up.profile_id = $3))"
        )

    async def list_page(
        self, q: str | None, is_blocked: bool | None, profile_id: UUID | None, limit: int, offset: int
    ) -> tuple[list[dict], int]:
        filters = {"q": like_pattern(q), "is_blocked": is_blocked, "profile_id": profile_id}
        total = await self._db.execute_query(
            f"SELECT COUNT(*) FROM users u {self._filters()}", filters, scalar=True
        )
        rows = await self._db.execute_query(
            f"SELECT {_ADMIN_COLUMNS} FROM users u {self._filters()} "
            "ORDER BY u.name, u.id LIMIT $4 OFFSET $5",
            {**filters, "limit": limit, "offset": offset},
        )
        return rows, total

    async def get_admin_row(self, user_id: UUID, db=None) -> dict | None:
        rows = await (db or self._db).execute_query(
            f"SELECT {_ADMIN_COLUMNS} FROM users u WHERE id = $1", {"id": user_id}
        )
        return rows[0] if rows else None

    async def create(
        self, name: str, email: str, password_hash: str, is_admin: bool, created_by: str | None, db=None
    ) -> UUID:
        return await (db or self._db).execute_query(
            "INSERT INTO users (name, external_id, password_hash, is_admin, created_by) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            {
                "name": name,
                "external_id": email,
                "password_hash": password_hash,
                "is_admin": is_admin,
                "created_by": created_by,
            },
            scalar=True,
        )

    async def update(self, user_id: UUID, fields: dict, db=None) -> bool:
        """`fields`: coluna → valor (name, external_id, is_admin, is_blocked, password_hash).
        Sempre atualiza `updated_at`. False se o usuário não existe."""
        rows = await (db or self._db).execute_query(
            f"UPDATE users SET {set_clause(fields, 2)}, updated_at = NOW() WHERE id = $1 RETURNING id",
            {"id": user_id, **fields},
        )
        return bool(rows)

    async def delete(self, user_id: UUID, db=None) -> bool:
        rows = await (db or self._db).execute_query(
            "DELETE FROM users WHERE id = $1 RETURNING id", {"id": user_id}
        )
        return bool(rows)

    async def has_history(self, user_id: UUID, db=None) -> bool:
        found = await (db or self._db).execute_query(
            "SELECT 1 FROM execution_history WHERE user_id = $1 LIMIT 1", {"user_id": user_id}
        )
        return bool(found)

    async def lock_active_admin_ids(self, db) -> set[UUID]:
        """Administradores ativos, com lock de linha até o fim da transação."""
        rows = await db.execute_query(
            "SELECT id FROM users WHERE is_admin AND NOT is_blocked FOR UPDATE"
        )
        return {row["id"] for row in rows}

    async def get_profiles(self, user_id: UUID, db=None) -> list[dict]:
        return await (db or self._db).execute_query(
            "SELECT p.id, p.name, p.is_active FROM profiles p "
            "JOIN user_profiles up ON up.profile_id = p.id WHERE up.user_id = $1 "
            "ORDER BY p.name, p.id",
            {"user_id": user_id},
        )

    async def existing_profile_ids(self, profile_ids: list[UUID], db=None) -> set[UUID]:
        rows = await (db or self._db).execute_query(
            "SELECT id FROM profiles WHERE id = ANY($1::uuid[])", {"ids": profile_ids}
        )
        return {row["id"] for row in rows}

    async def replace_profiles(self, user_id: UUID, profile_ids: list[UUID], db) -> None:
        await db.execute("DELETE FROM user_profiles WHERE user_id = $1", user_id)
        if profile_ids:
            await db.execute(
                "INSERT INTO user_profiles (user_id, profile_id) "
                "SELECT $1, UNNEST($2::uuid[])",
                user_id,
                profile_ids,
            )
