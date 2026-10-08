"""Serviços de usuário e perfil da API admin — corridas e ramos de erro (F17 A6).

Chamam os serviços direto, sobre os repositórios em memória de `admin_fakes.py`, injetando
`UniqueViolationError`/`ForeignKeyViolationError` como o Postgres faria numa corrida.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest

from schemas.admin import (
    AdminTokenNotFoundError,
    EmailAlreadyExistsError,
    InvalidReferenceError,
    ProfileCreate,
    ProfileNameAlreadyExistsError,
    ProfileNotFoundError,
    ProfileUpdate,
    UserCreate,
    UserHasHistoryError,
    UserNotFoundError,
    UserUpdate,
)
from schemas.auth import AuthenticatedUser
from services.profile_admin_service import ProfileAdminService
from services.user_admin_service import UserAdminService
from tests.admin_fakes import FakeDb, FakeProfileRepo, FakeTokenRepo, FakeUserRepo, Store

GOOD_PASSWORD = "Nova#Senha1"


class World:
    def __init__(self) -> None:
        self.store = Store()
        self.db = FakeDb(self.store)
        self.users = FakeUserRepo(self.store)
        self.profiles = FakeProfileRepo(self.store)
        self.admin_id = self.store.add_user("Admin", "admin", is_admin=True)
        self.user_id = self.store.add_user("Maria", "maria@empresa.com")
        self.actor = AuthenticatedUser(id=self.admin_id, name="Admin")
        self.user_service = UserAdminService(self.db, self.users, FakeTokenRepo(self.store))
        self.profile_service = ProfileAdminService(self.db, self.profiles)


@pytest.fixture
def w():
    return World()


def _race(exc_type):
    return AsyncMock(side_effect=exc_type("corrida"))


class TestUserServiceRaces:
    @pytest.mark.asyncio
    async def test_create_user_unique_violation_becomes_email_already_exists_and_rolls_back(self, w):
        w.users.create = _race(asyncpg.UniqueViolationError)
        before = set(w.store.users)

        with pytest.raises(EmailAlreadyExistsError):
            await w.user_service.create_user(
                UserCreate(name="Novo", email="novo@empresa.com", password=GOOD_PASSWORD), w.actor
            )

        assert set(w.store.users) == before

    @pytest.mark.asyncio
    async def test_update_user_unique_violation_becomes_email_already_exists(self, w):
        w.users.update = _race(asyncpg.UniqueViolationError)

        with pytest.raises(EmailAlreadyExistsError):
            await w.user_service.update_user(w.user_id, UserUpdate(name="Outro"), w.actor)

    @pytest.mark.asyncio
    async def test_update_user_without_effective_fields_writes_nothing(self, w):
        w.users.update = AsyncMock()

        detail = await w.user_service.update_user(w.user_id, UserUpdate(name=None, email=None), w.actor)

        assert detail.email == "maria@empresa.com"
        w.users.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_user_keeping_own_email_is_not_a_conflict(self, w):
        detail = await w.user_service.update_user(
            w.user_id, UserUpdate(email="  MARIA@empresa.com "), w.actor
        )

        assert detail.email == "maria@empresa.com"

    @pytest.mark.asyncio
    async def test_update_user_with_other_users_email_conflicts(self, w):
        w.store.add_user("Outro", "outro@empresa.com")

        with pytest.raises(EmailAlreadyExistsError):
            await w.user_service.update_user(w.user_id, UserUpdate(email="outro@empresa.com"), w.actor)

    @pytest.mark.asyncio
    async def test_delete_user_foreign_key_violation_becomes_has_history(self, w):
        w.users.delete = _race(asyncpg.ForeignKeyViolationError)

        with pytest.raises(UserHasHistoryError):
            await w.user_service.delete_user(w.user_id, w.actor)

        assert w.user_id in w.store.users

    @pytest.mark.asyncio
    async def test_delete_user_with_history_is_refused_and_user_kept(self, w):
        w.store.history_user_ids.add(w.user_id)

        with pytest.raises(UserHasHistoryError):
            await w.user_service.delete_user(w.user_id, w.actor)


class TestUserServiceNotFound:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("call", [
        lambda s, a, uid: s.update_user(uid, UserUpdate(name="X"), a),
        lambda s, a, uid: s.delete_user(uid, a),
        lambda s, a, uid: s.reset_password(uid, GOOD_PASSWORD, a),
        lambda s, a, uid: s.set_blocked(uid, True, a),
        lambda s, a, uid: s.set_blocked(uid, False, a),
        lambda s, a, uid: s.set_profiles(uid, [], a),
        lambda s, a, uid: s.list_tokens(uid),
        lambda s, a, uid: s.revoke_token(uid, uuid4(), a),
        lambda s, a, uid: s.revoke_all_tokens(uid, a),
    ])
    async def test_unknown_user_is_404(self, w, call):
        with pytest.raises(UserNotFoundError):
            await call(w.user_service, w.actor, uuid4())

    @pytest.mark.asyncio
    async def test_password_write_for_user_removed_meanwhile_is_not_found(self, w):
        """O usuário some entre a checagem e a gravação do hash (update devolve False)."""
        w.users.update = AsyncMock(return_value=False)

        with pytest.raises(UserNotFoundError):
            await w.user_service.reset_password(w.user_id, GOOD_PASSWORD, w.actor)

    @pytest.mark.asyncio
    async def test_unknown_token_is_404(self, w):
        with pytest.raises(AdminTokenNotFoundError):
            await w.user_service.revoke_token(w.user_id, uuid4(), w.actor)

    @pytest.mark.asyncio
    async def test_me_and_own_password_for_removed_user(self, w):
        ghost = AuthenticatedUser(id=uuid4(), name="Fantasma")

        with pytest.raises(UserNotFoundError):
            await w.user_service.get_me(ghost)
        with pytest.raises(UserNotFoundError):
            await w.user_service.change_own_password(ghost, "x", GOOD_PASSWORD)

    @pytest.mark.asyncio
    async def test_set_profiles_with_unknown_profile_is_invalid_reference(self, w):
        missing = uuid4()

        with pytest.raises(InvalidReferenceError) as raised:
            await w.user_service.set_profiles(w.user_id, [missing], w.actor)

        assert raised.value.missing == [missing]


class TestProfileServiceEdges:
    @pytest.mark.asyncio
    async def test_create_profile_unique_violation(self, w):
        w.store.add_profile("Comercial")

        with pytest.raises(ProfileNameAlreadyExistsError):
            await w.profile_service.create_profile(ProfileCreate(name="Comercial"), w.actor)

    @pytest.mark.asyncio
    async def test_update_profile_null_name_and_is_active_means_nothing_to_write(self, w):
        pid = w.store.add_profile("Comercial")
        w.profiles.update = AsyncMock()

        detail = await w.profile_service.update_profile(
            pid, ProfileUpdate(name=None, is_active=None), w.actor
        )

        assert detail.name == "Comercial"
        w.profiles.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_profile_null_description_clears_it(self, w):
        pid = w.store.add_profile("Comercial")
        w.store.profiles[pid]["description"] = "antiga"

        detail = await w.profile_service.update_profile(pid, ProfileUpdate(description=None), w.actor)

        assert detail.description is None

    @pytest.mark.asyncio
    async def test_update_profile_name_collision_and_not_found(self, w):
        w.store.add_profile("Comercial")
        other = w.store.add_profile("Financeiro")

        with pytest.raises(ProfileNameAlreadyExistsError):
            await w.profile_service.update_profile(other, ProfileUpdate(name="Comercial"), w.actor)
        with pytest.raises(ProfileNotFoundError):
            await w.profile_service.update_profile(uuid4(), ProfileUpdate(name="X"), w.actor)

    @pytest.mark.asyncio
    async def test_delete_unknown_profile_is_404(self, w):
        with pytest.raises(ProfileNotFoundError):
            await w.profile_service.delete_profile(uuid4(), w.actor)

    @pytest.mark.asyncio
    async def test_replace_users_and_analyses_validate_profile_and_references(self, w):
        pid = w.store.add_profile("Comercial")
        missing = uuid4()

        with pytest.raises(ProfileNotFoundError):
            await w.profile_service.set_users(uuid4(), [], w.actor)
        with pytest.raises(InvalidReferenceError):
            await w.profile_service.set_users(pid, [missing], w.actor)
        with pytest.raises(InvalidReferenceError):
            await w.profile_service.set_analyses(pid, [missing], w.actor)

        detail = await w.profile_service.set_users(pid, [w.user_id, w.user_id], w.actor)  # duplicado tolerado
        assert [u.id for u in detail.users] == [w.user_id]
        detail = await w.profile_service.set_users(pid, [], w.actor)  # lista vazia limpa o vínculo
        assert detail.users == []
