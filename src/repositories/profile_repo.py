"""Permissões usuário → perfil → analyses (F12 §4.4) e administração de perfis (F23 §4.1).

Os métodos administrativos aceitam um `db` opcional (adapter ou `Transaction`).
"""

from uuid import UUID

from adapters.postgresql import PostgreSQLAdapter
from repositories.sql_helpers import like_pattern, set_clause

_SUMMARY = (
    "p.id, p.name, p.description, p.is_active, p.created_at, p.updated_at, "
    "(SELECT COUNT(*) FROM user_profiles up WHERE up.profile_id = p.id) AS users_count, "
    "(SELECT COUNT(*) FROM profile_analyses pa WHERE pa.profile_id = p.id) AS analyses_count"
)
_FILTERS = (
    "WHERE ($1::text IS NULL OR p.name ILIKE $1 ESCAPE '\\' OR p.description ILIKE $1 ESCAPE '\\') "
    "AND ($2::bool IS NULL OR p.is_active = $2)"
)


class ProfileRepository:
    def __init__(self, config_db_adapter: PostgreSQLAdapter) -> None:
        self._db = config_db_adapter

    async def get_allowed_analysis_ids(self, user_id: UUID) -> set[UUID]:
        """Mesma regra de AnalysisRepository.get_allowed_for_user(): analyses ativas
        vinculadas a um perfil ativo vinculado ao usuário. Usado só pela
        revalidação de call_tool() (AuthService.is_analysis_allowed)."""
        rows = await self._db.execute_query(
            "SELECT DISTINCT a.id "
            "FROM analyses a "
            "JOIN profile_analyses pa ON pa.analysis_id = a.id "
            "JOIN user_profiles up ON up.profile_id = pa.profile_id "
            "JOIN profiles p ON p.id = pa.profile_id "
            "WHERE up.user_id = $1 AND a.is_active = true AND p.is_active = true",
            {"user_id": user_id},
        )
        return {row["id"] for row in rows}

    # ---- F23: administração ----

    async def list_page(
        self, q: str | None, is_active: bool | None, limit: int, offset: int
    ) -> tuple[list[dict], int]:
        filters = {"q": like_pattern(q), "is_active": is_active}
        total = await self._db.execute_query(
            f"SELECT COUNT(*) FROM profiles p {_FILTERS}", filters, scalar=True
        )
        rows = await self._db.execute_query(
            f"SELECT {_SUMMARY} FROM profiles p {_FILTERS} ORDER BY p.name, p.id LIMIT $3 OFFSET $4",
            {**filters, "limit": limit, "offset": offset},
        )
        return rows, total

    async def get_summary(self, profile_id: UUID, db=None) -> dict | None:
        rows = await (db or self._db).execute_query(
            f"SELECT {_SUMMARY} FROM profiles p WHERE p.id = $1", {"id": profile_id}
        )
        return rows[0] if rows else None

    async def create(self, name: str, description: str | None, is_active: bool, db=None) -> UUID:
        return await (db or self._db).execute_query(
            "INSERT INTO profiles (name, description, is_active) VALUES ($1, $2, $3) RETURNING id",
            {"name": name, "description": description, "is_active": is_active},
            scalar=True,
        )

    async def update(self, profile_id: UUID, fields: dict, db=None) -> bool:
        rows = await (db or self._db).execute_query(
            f"UPDATE profiles SET {set_clause(fields, 2)}, updated_at = NOW() WHERE id = $1 RETURNING id",
            {"id": profile_id, **fields},
        )
        return bool(rows)

    async def delete(self, profile_id: UUID, db=None) -> bool:
        """Físico: user_profiles e profile_analyses caem em cascata."""
        rows = await (db or self._db).execute_query(
            "DELETE FROM profiles WHERE id = $1 RETURNING id", {"id": profile_id}
        )
        return bool(rows)

    async def get_users(self, profile_id: UUID, db=None) -> list[dict]:
        return await (db or self._db).execute_query(
            "SELECT u.id, u.name, u.external_id AS email, u.is_blocked FROM users u "
            "JOIN user_profiles up ON up.user_id = u.id WHERE up.profile_id = $1 "
            "ORDER BY u.name, u.id",
            {"profile_id": profile_id},
        )

    async def get_analyses(self, profile_id: UUID, db=None) -> list[dict]:
        return await (db or self._db).execute_query(
            "SELECT a.id, a.name, a.is_active FROM analyses a "
            "JOIN profile_analyses pa ON pa.analysis_id = a.id WHERE pa.profile_id = $1 "
            "ORDER BY a.name, a.id",
            {"profile_id": profile_id},
        )

    async def existing_ids(self, table: str, ids: list[UUID], db=None) -> set[UUID]:
        """`table`: 'users', 'analyses' ou 'profiles' (fixo no código)."""
        assert table in ("users", "analyses", "profiles")
        rows = await (db or self._db).execute_query(
            f"SELECT id FROM {table} WHERE id = ANY($1::uuid[])", {"ids": ids}
        )
        return {row["id"] for row in rows}

    async def replace_analyses(self, profile_id: UUID, analysis_ids: list[UUID], db) -> None:
        await db.execute("DELETE FROM profile_analyses WHERE profile_id = $1", profile_id)
        if analysis_ids:
            await db.execute(
                "INSERT INTO profile_analyses (profile_id, analysis_id) SELECT $1, UNNEST($2::uuid[])",
                profile_id,
                analysis_ids,
            )

    async def replace_users(self, profile_id: UUID, user_ids: list[UUID], db) -> None:
        await db.execute("DELETE FROM user_profiles WHERE profile_id = $1", profile_id)
        if user_ids:
            await db.execute(
                "INSERT INTO user_profiles (profile_id, user_id) SELECT $1, UNNEST($2::uuid[])",
                profile_id,
                user_ids,
            )
