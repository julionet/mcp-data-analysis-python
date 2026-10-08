"""Regras de administração de perfis e seus vínculos — F23 §4.4.3."""

from uuid import UUID

import asyncpg

from repositories.profile_repo import ProfileRepository
from schemas.admin import (
    InvalidReferenceError,
    Page,
    ProfileAnalysisRef,
    ProfileCreate,
    ProfileDetail,
    ProfileNameAlreadyExistsError,
    ProfileNotFoundError,
    ProfileSummary,
    ProfileUpdate,
    ProfileUserRef,
)
from schemas.auth import AuthenticatedUser
from services.user_admin_service import log_admin_action


class ProfileAdminService:
    def __init__(self, db, profile_repo: ProfileRepository) -> None:
        self._db = db
        self._profiles = profile_repo

    async def _detail(self, profile_id: UUID, db=None) -> ProfileDetail:
        summary = await self._profiles.get_summary(profile_id, db)
        if summary is None:
            raise ProfileNotFoundError()
        users = await self._profiles.get_users(profile_id, db)
        analyses = await self._profiles.get_analyses(profile_id, db)
        return ProfileDetail(
            **summary,
            users=[ProfileUserRef(**u) for u in users],
            analyses=[ProfileAnalysisRef(**a) for a in analyses],
        )

    async def list_profiles(
        self, q: str | None, is_active: bool | None, limit: int, offset: int
    ) -> Page[ProfileSummary]:
        rows, total = await self._profiles.list_page(q, is_active, limit, offset)
        return Page[ProfileSummary](
            items=[ProfileSummary(**row) for row in rows], total=total, limit=limit, offset=offset
        )

    async def get_profile(self, profile_id: UUID) -> ProfileDetail:
        return await self._detail(profile_id)

    async def create_profile(self, data: ProfileCreate, actor: AuthenticatedUser) -> ProfileDetail:
        try:
            profile_id = await self._profiles.create(data.name, data.description, data.is_active)
        except asyncpg.UniqueViolationError as exc:
            raise ProfileNameAlreadyExistsError() from exc
        log_admin_action(actor.id, "create_profile", "profile", profile_id)
        return await self._detail(profile_id)

    async def update_profile(
        self, profile_id: UUID, data: ProfileUpdate, actor: AuthenticatedUser
    ) -> ProfileDetail:
        fields = {
            name: getattr(data, name)
            for name in ("name", "description", "is_active")
            if name in data.model_fields_set
        }
        # name e is_active são NOT NULL: enviar null equivale a não enviar
        fields = {k: v for k, v in fields.items() if k == "description" or v is not None}
        if fields:
            try:
                if not await self._profiles.update(profile_id, fields):
                    raise ProfileNotFoundError()
            except asyncpg.UniqueViolationError as exc:
                raise ProfileNameAlreadyExistsError() from exc
            log_admin_action(actor.id, "update_profile", "profile", profile_id)
        return await self._detail(profile_id)

    async def delete_profile(self, profile_id: UUID, actor: AuthenticatedUser) -> None:
        if not await self._profiles.delete(profile_id):
            raise ProfileNotFoundError()
        log_admin_action(actor.id, "delete_profile", "profile", profile_id)

    async def _replace(
        self, profile_id: UUID, ids: list[UUID], table: str, label: str, replace, action: str,
        actor: AuthenticatedUser,
    ) -> ProfileDetail:
        ids = list(dict.fromkeys(ids))
        async with self._db.transaction() as tx:
            if await self._profiles.get_summary(profile_id, tx) is None:
                raise ProfileNotFoundError()
            if ids:
                existing = await self._profiles.existing_ids(table, ids, tx)
                missing = [i for i in ids if i not in existing]
                if missing:
                    raise InvalidReferenceError(label, missing)
            await replace(profile_id, ids, tx)
        log_admin_action(actor.id, action, "profile", profile_id)
        return await self._detail(profile_id)

    async def set_analyses(
        self, profile_id: UUID, analysis_ids: list[UUID], actor: AuthenticatedUser
    ) -> ProfileDetail:
        return await self._replace(
            profile_id, analysis_ids, "analyses", "Analyses",
            self._profiles.replace_analyses, "set_profile_analyses", actor,
        )

    async def set_users(
        self, profile_id: UUID, user_ids: list[UUID], actor: AuthenticatedUser
    ) -> ProfileDetail:
        return await self._replace(
            profile_id, user_ids, "users", "Usuários",
            self._profiles.replace_users, "set_profile_users", actor,
        )
