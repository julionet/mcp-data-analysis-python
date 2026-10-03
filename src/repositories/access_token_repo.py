"""Acesso a `access_tokens` no Config DB — F12_AUTENTICACAO_PERFIS.md §4.4.

Só o hash SHA-256 do token é persistido. As datas são TIMESTAMPTZ, então o
asyncpg devolve `datetime` com fuso e a comparação com now(UTC) funciona.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from adapters.postgresql import PostgreSQLAdapter

_COLUMNS = "id, user_id, token_hash, label, expires_at, revoked_at"


@dataclass
class AccessToken:
    id: UUID
    user_id: UUID
    token_hash: str
    label: str | None
    expires_at: datetime
    revoked_at: datetime | None


def _to_token(row: dict) -> AccessToken:
    return AccessToken(
        id=row["id"],
        user_id=row["user_id"],
        token_hash=row["token_hash"],
        label=row["label"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
    )


class AccessTokenRepository:
    def __init__(self, config_db_adapter: PostgreSQLAdapter) -> None:
        self._db = config_db_adapter

    async def get_by_hash(self, token_hash: str) -> AccessToken | None:
        rows = await self._db.execute_query(
            f"SELECT {_COLUMNS} FROM access_tokens WHERE token_hash = $1",
            {"token_hash": token_hash},
        )
        return _to_token(rows[0]) if rows else None

    async def create(
        self, user_id: UUID, token_hash: str, expires_at: datetime, label: str | None
    ) -> AccessToken:
        rows = await self._db.execute_query(
            "INSERT INTO access_tokens (user_id, token_hash, expires_at, label) "
            f"VALUES ($1, $2, $3, $4) RETURNING {_COLUMNS}",
            {"user_id": user_id, "token_hash": token_hash, "expires_at": expires_at, "label": label},
        )
        return _to_token(rows[0])

    async def touch_last_used(self, token_id: UUID) -> None:
        await self._db.execute(
            "UPDATE access_tokens SET last_used_at = NOW() WHERE id = $1", token_id
        )

    async def revoke(self, token_id: UUID) -> None:
        """Idempotente: um token já revogado mantém o revoked_at original."""
        await self._db.execute(
            "UPDATE access_tokens SET revoked_at = NOW() WHERE id = $1 AND revoked_at IS NULL",
            token_id,
        )
