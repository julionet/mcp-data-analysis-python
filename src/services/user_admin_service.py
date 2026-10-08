"""Regras de administração de usuários, senhas e tokens — F23 §4.4.2/§4.4.4.

`db` é o adapter do Config DB (ou qualquer objeto com `transaction()`): escritas
multi-tabela e as verificações de proteção rodam dentro de uma transação.
"""

import asyncio
import logging
from uuid import UUID

import asyncpg

from repositories.access_token_repo import AccessTokenRepository
from repositories.user_repo import UserRepository
from schemas.admin import (
    AdminTokenNotFoundError,
    EmailAlreadyExistsError,
    InvalidCurrentPasswordError,
    InvalidPasswordError,
    InvalidReferenceError,
    LastAdminProtectedError,
    Me,
    Page,
    ProfileRef,
    SelfProtectedError,
    TokenInfo,
    UserCreate,
    UserDetail,
    UserHasHistoryError,
    UserNotFoundError,
    UserSummary,
    UserUpdate,
)
from schemas.auth import AuthenticatedUser
from security.password_hash import (
    PasswordPolicyError,
    hash_password,
    validate_password_policy,
    verify_password,
)

logger = logging.getLogger(__name__)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def check_password_policy(password: str) -> None:
    try:
        validate_password_policy(password)
    except PasswordPolicyError as exc:
        raise InvalidPasswordError(exc.reason) from exc


def log_admin_action(actor_id: UUID, action: str, target_type: str, target_id: UUID) -> None:
    """Sem senha, hash, token nem e-mail (F23 §4.3)."""
    logger.info(
        "admin_action actor_id=%s action=%s target_type=%s target_id=%s",
        actor_id, action, target_type, target_id,
    )


class UserAdminService:
    def __init__(self, db, user_repo: UserRepository, token_repo: AccessTokenRepository) -> None:
        self._db = db
        self._users = user_repo
        self._tokens = token_repo

    # ---- leitura ----

    async def _detail(self, user_id: UUID, db=None) -> UserDetail:
        row = await self._users.get_admin_row(user_id, db)
        if row is None:
            raise UserNotFoundError()
        profiles = await self._users.get_profiles(user_id, db)
        active = await self._tokens.count_active(user_id)
        return UserDetail(
            **row,
            email=row["external_id"],
            profiles=[ProfileRef(**p) for p in profiles],
            active_tokens=active,
        )

    async def list_users(
        self, q: str | None, is_blocked: bool | None, profile_id: UUID | None, limit: int, offset: int
    ) -> Page[UserSummary]:
        rows, total = await self._users.list_page(q, is_blocked, profile_id, limit, offset)
        items = [UserSummary(**row, email=row["external_id"]) for row in rows]
        return Page[UserSummary](items=items, total=total, limit=limit, offset=offset)

    async def get_user(self, user_id: UUID) -> UserDetail:
        return await self._detail(user_id)

    # ---- escrita ----

    async def _check_profiles_exist(self, profile_ids: list[UUID], db) -> None:
        if not profile_ids:
            return
        missing = [i for i in profile_ids if i not in await self._users.existing_profile_ids(profile_ids, db)]
        if missing:
            raise InvalidReferenceError("Perfis", missing)

    async def create_user(self, data: UserCreate, actor: AuthenticatedUser) -> UserDetail:
        check_password_policy(data.password)
        email = normalize_email(data.email)
        if await self._users.get_by_external_id(email) is not None:
            raise EmailAlreadyExistsError()
        password_hash = await hash_password(data.password)
        profile_ids = list(dict.fromkeys(data.profile_ids))
        actor_row = await self._users.get_by_id(actor.id)
        created_by = actor_row.external_id if actor_row else None
        try:
            async with self._db.transaction() as tx:
                await self._check_profiles_exist(profile_ids, tx)
                user_id = await self._users.create(
                    data.name, email, password_hash, data.is_admin, created_by, tx
                )
                await self._users.replace_profiles(user_id, profile_ids, tx)
        except asyncpg.UniqueViolationError as exc:
            raise EmailAlreadyExistsError() from exc
        log_admin_action(actor.id, "create_user", "user", user_id)
        return await self._detail(user_id)

    async def _ensure_not_last_admin(self, user_id: UUID, tx) -> None:
        """Dentro da transação, com lock nos administradores ativos: o usuário não pode
        ser o único restante."""
        admins = await self._users.lock_active_admin_ids(tx)
        if user_id in admins and not (admins - {user_id}):
            raise LastAdminProtectedError()

    async def update_user(self, user_id: UUID, data: UserUpdate, actor: AuthenticatedUser) -> UserDetail:
        fields: dict = {}
        if "name" in data.model_fields_set and data.name is not None:
            fields["name"] = data.name
        if "email" in data.model_fields_set and data.email is not None:
            fields["external_id"] = normalize_email(data.email)
        demoting = data.is_admin is False
        if data.is_admin is not None:
            fields["is_admin"] = data.is_admin
        if demoting and user_id == actor.id:
            raise SelfProtectedError()
        if not fields:
            return await self._detail(user_id)
        if "external_id" in fields:
            other = await self._users.get_by_external_id(fields["external_id"])
            if other is not None and other.id != user_id:
                raise EmailAlreadyExistsError()
        try:
            async with self._db.transaction() as tx:
                target = await self._users.get_by_id(user_id, tx)
                if target is None:
                    raise UserNotFoundError()
                if demoting and target.is_admin and not target.is_blocked:
                    await self._ensure_not_last_admin(user_id, tx)
                await self._users.update(user_id, fields, tx)
        except asyncpg.UniqueViolationError as exc:
            raise EmailAlreadyExistsError() from exc
        log_admin_action(actor.id, "update_user", "user", user_id)
        return await self._detail(user_id)

    async def delete_user(self, user_id: UUID, actor: AuthenticatedUser) -> None:
        if user_id == actor.id:
            raise SelfProtectedError()
        try:
            async with self._db.transaction() as tx:
                target = await self._users.get_by_id(user_id, tx)
                if target is None:
                    raise UserNotFoundError()
                if target.is_admin and not target.is_blocked:
                    await self._ensure_not_last_admin(user_id, tx)
                if await self._users.has_history(user_id, tx):
                    raise UserHasHistoryError()
                await self._users.delete(user_id, tx)
        except asyncpg.ForeignKeyViolationError as exc:
            raise UserHasHistoryError() from exc
        log_admin_action(actor.id, "delete_user", "user", user_id)

    async def reset_password(self, user_id: UUID, password: str, actor: AuthenticatedUser) -> None:
        check_password_policy(password)
        if await self._users.get_admin_row(user_id) is None:
            raise UserNotFoundError()
        password_hash = await hash_password(password)
        await self._write_password(user_id, password_hash)
        log_admin_action(actor.id, "reset_password", "user", user_id)

    async def _write_password(self, user_id: UUID, password_hash: str) -> None:
        """Grava o hash e revoga todos os tokens do usuário, na mesma transação."""
        async with self._db.transaction() as tx:
            if not await self._users.update(user_id, {"password_hash": password_hash}, tx):
                raise UserNotFoundError()
            await self._tokens.revoke_all(user_id, tx)

    async def set_blocked(self, user_id: UUID, blocked: bool, actor: AuthenticatedUser) -> UserDetail:
        if blocked and user_id == actor.id:
            raise SelfProtectedError()
        async with self._db.transaction() as tx:
            target = await self._users.get_by_id(user_id, tx)
            if target is None:
                raise UserNotFoundError()
            if blocked and target.is_admin and not target.is_blocked:
                await self._ensure_not_last_admin(user_id, tx)
            await self._users.update(user_id, {"is_blocked": blocked}, tx)
        log_admin_action(actor.id, "block_user" if blocked else "unblock_user", "user", user_id)
        return await self._detail(user_id)

    async def set_profiles(
        self, user_id: UUID, profile_ids: list[UUID], actor: AuthenticatedUser
    ) -> UserDetail:
        profile_ids = list(dict.fromkeys(profile_ids))
        async with self._db.transaction() as tx:
            if await self._users.get_by_id(user_id, tx) is None:
                raise UserNotFoundError()
            await self._check_profiles_exist(profile_ids, tx)
            await self._users.replace_profiles(user_id, profile_ids, tx)
        log_admin_action(actor.id, "set_user_profiles", "user", user_id)
        return await self._detail(user_id)

    # ---- tokens ----

    async def list_tokens(self, user_id: UUID) -> list[TokenInfo]:
        if await self._users.get_admin_row(user_id) is None:
            raise UserNotFoundError()
        return [TokenInfo(**row) for row in await self._tokens.list_by_user(user_id)]

    async def revoke_token(self, user_id: UUID, token_id: UUID, actor: AuthenticatedUser) -> None:
        if await self._users.get_admin_row(user_id) is None:
            raise UserNotFoundError()
        if not await self._tokens.revoke_for_user(token_id, user_id):
            raise AdminTokenNotFoundError()
        log_admin_action(actor.id, "revoke_token", "token", token_id)

    async def revoke_all_tokens(self, user_id: UUID, actor: AuthenticatedUser) -> int:
        if await self._users.get_admin_row(user_id) is None:
            raise UserNotFoundError()
        revoked = await self._tokens.revoke_all(user_id)
        log_admin_action(actor.id, "revoke_all_tokens", "user", user_id)
        return revoked

    # ---- autosserviço ----

    async def get_me(self, user: AuthenticatedUser) -> Me:
        row = await self._users.get_admin_row(user.id)
        if row is None:
            raise UserNotFoundError()
        profiles = await self._users.get_profiles(user.id)
        return Me(
            id=row["id"],
            name=row["name"],
            email=row["external_id"],
            is_admin=row["is_admin"],
            profiles=[ProfileRef(**p) for p in profiles],
        )

    async def change_own_password(
        self, user: AuthenticatedUser, current_password: str, new_password: str
    ) -> None:
        record = await self._users.get_by_id(user.id)
        if record is None:
            raise UserNotFoundError()
        if not await asyncio.to_thread(verify_password, current_password, record.password_hash):
            raise InvalidCurrentPasswordError()
        check_password_policy(new_password)
        await self._write_password(user.id, await hash_password(new_password))
        log_admin_action(user.id, "change_own_password", "user", user.id)
