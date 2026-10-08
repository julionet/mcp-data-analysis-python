"""Integração (Config DB real) — F23_API_ADMIN_USUARIOS_PERFIS.md §6.2.

Serviços e repositórios administrativos contra o banco de verdade: SQL, transação com
rollback, cascatas, FOR UPDATE e unicidade. Pula sozinho se não há banco ou se faltam as
tabelas do F12 / a coluna `users.is_admin` (aplicar database/schema.sql). Tudo o que o
teste cria tem o prefixo `f23-it` e é removido no fim.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from adapters.postgresql import PostgreSQLAdapter
from config import settings
from repositories.access_token_repo import AccessTokenRepository
from repositories.profile_repo import ProfileRepository
from repositories.user_repo import UserRepository
from schemas.admin import (
    EmailAlreadyExistsError,
    InvalidReferenceError,
    LastAdminProtectedError,
    ProfileCreate,
    UserCreate,
    UserHasHistoryError,
    UserUpdate,
)
from schemas.auth import AuthenticatedUser
from security.password_hash import verify_password
from services.profile_admin_service import ProfileAdminService
from services.user_admin_service import UserAdminService

pytestmark = pytest.mark.integration  # F17: exige o Config DB (pulado sozinho sem banco)

PASSWORD = "Nova#Senha1"


@pytest_asyncio.fixture
async def db():
    adapter = PostgreSQLAdapter(
        {
            "host": settings.postgres_config_host,
            "port": settings.postgres_config_port,
            "user": settings.postgres_config_user,
            "password": settings.postgres_config_password,
            "database": settings.postgres_config_database,
        }
    )
    try:
        await adapter.connect()
    except Exception:
        pytest.skip("Config DB indisponível")
    try:
        has_column = await adapter.execute_query(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'is_admin'"
        )
        if not has_column or await adapter.execute_query("SELECT to_regclass('public.access_tokens')", scalar=True) is None:
            pytest.skip("Tabelas do F12/F23 ausentes — aplique database/schema.sql")
        yield adapter
    finally:
        await _cleanup(adapter)
        await adapter.disconnect()


async def _cleanup(db):
    await db.execute("DELETE FROM execution_history WHERE user_id IN (SELECT id FROM users WHERE external_id LIKE 'f23-it%')")
    await db.execute("DELETE FROM analyses WHERE name LIKE 'f23-it%'")
    await db.execute("DELETE FROM data_sources WHERE name LIKE 'f23-it%'")
    await db.execute("DELETE FROM profiles WHERE name LIKE 'f23-it%'")
    await db.execute("DELETE FROM users WHERE external_id LIKE 'f23-it%'")


@pytest.fixture
def services(db):
    users, tokens, profiles = UserRepository(db), AccessTokenRepository(db), ProfileRepository(db)
    return UserAdminService(db, users, tokens), ProfileAdminService(db, profiles), users, tokens, profiles


async def _make_admin(db, email="f23-it-actor@example.com", blocked=False) -> AuthenticatedUser:
    user_id = await db.execute_query(
        "INSERT INTO users (name, external_id, password_hash, is_admin, is_blocked) "
        "VALUES ('Ator', $1, 'x', true, $2) RETURNING id",
        {"email": email, "blocked": blocked}, scalar=True,
    )
    return AuthenticatedUser(id=user_id, name="Ator")


async def _make_analysis(db, name="f23-it-analysis"):
    ds = await db.execute_query(
        "INSERT INTO data_sources (name, type, connection_config) VALUES ('f23-it-ds', 'postgresql', '{}') "
        "ON CONFLICT (name) DO UPDATE SET type = 'postgresql' RETURNING id", scalar=True)
    return await db.execute_query(
        "INSERT INTO analyses (name, data_source_id, parameters) VALUES ($1, $2, '{}') RETURNING id",
        {"name": name, "ds": ds}, scalar=True)


@pytest.mark.asyncio
async def test_transaction_commits_and_rolls_back(db):
    async with db.transaction() as tx:
        await tx.execute("INSERT INTO profiles (name) VALUES ('f23-it-commit')")
    assert await db.execute_query("SELECT 1 FROM profiles WHERE name = 'f23-it-commit'")

    with pytest.raises(RuntimeError):
        async with db.transaction() as tx:
            await tx.execute("INSERT INTO profiles (name) VALUES ('f23-it-rollback')")
            raise RuntimeError("boom")
    assert not await db.execute_query("SELECT 1 FROM profiles WHERE name = 'f23-it-rollback'")


@pytest.mark.asyncio
async def test_create_user_with_missing_profile_rolls_back(db, services):
    user_service, *_ = services
    actor = await _make_admin(db)
    from uuid import uuid4

    with pytest.raises(InvalidReferenceError):
        await user_service.create_user(
            UserCreate(name="N", email="f23-it-new@example.com", password=PASSWORD, profile_ids=[uuid4()]), actor)
    assert not await db.execute_query("SELECT 1 FROM users WHERE external_id = 'f23-it-new@example.com'")


@pytest.mark.asyncio
async def test_user_lifecycle_filters_cascades_and_unique(db, services):
    user_service, profile_service, users, tokens, _ = services
    actor = await _make_admin(db)
    profile = await profile_service.create_profile(ProfileCreate(name="f23-it-prof"), actor)

    created = await user_service.create_user(
        UserCreate(name="Maria", email="f23-it-maria@example.com", password=PASSWORD,
                   profile_ids=[profile.id]), actor)
    assert created.created_by == "f23-it-actor@example.com" and [p.id for p in created.profiles] == [profile.id]
    stored = await users.get_by_id(created.id)
    assert verify_password(PASSWORD, stored.password_hash)

    with pytest.raises(EmailAlreadyExistsError):
        await user_service.create_user(
            UserCreate(name="Dup", email="F23-IT-maria@example.com", password=PASSWORD), actor)
    with pytest.raises(EmailAlreadyExistsError):
        await user_service.update_user(created.id, UserUpdate(email="f23-it-actor@example.com"), actor)

    page = await user_service.list_users("f23-it-mar", None, profile.id, 50, 0)
    assert page.total == 1 and page.items[0].email == "f23-it-maria@example.com"
    assert (await user_service.list_users("f23-it_", None, None, 50, 0)).total == 0  # '_' escapado
    assert (await user_service.list_users("f23-it", True, None, 50, 0)).total == 0

    expires = datetime.now(timezone.utc) + timedelta(days=1)
    await tokens.create(created.id, "a" * 64, expires, "t1")
    await tokens.create(created.id, "b" * 64, expires, "t2")
    assert (await user_service.get_user(created.id)).active_tokens == 2
    await user_service.reset_password(created.id, "Outra#Senha2", actor)
    assert (await user_service.get_user(created.id)).active_tokens == 0
    assert len(await user_service.list_tokens(created.id)) == 2

    profile_detail = await profile_service.get_profile(profile.id)
    assert profile_detail.users_count == 1 and profile_detail.users[0].email == "f23-it-maria@example.com"

    await user_service.delete_user(created.id, actor)
    assert not await db.execute_query("SELECT 1 FROM access_tokens WHERE token_hash = $1", {"h": "a" * 64})
    assert (await profile_service.get_profile(profile.id)).users_count == 0

    await profile_service.delete_profile(profile.id, actor)
    assert not await db.execute_query("SELECT 1 FROM profiles WHERE id = $1", {"id": profile.id})


@pytest.mark.asyncio
async def test_delete_user_with_history_refused(db, services):
    user_service, _, users, *_ = services
    actor = await _make_admin(db)
    created = await user_service.create_user(
        UserCreate(name="H", email="f23-it-hist@example.com", password=PASSWORD), actor)
    analysis = await _make_analysis(db)
    await db.execute(
        "INSERT INTO execution_history (analysis_id, user_id, status) VALUES ($1, $2, 'success')", analysis, created.id)

    with pytest.raises(UserHasHistoryError):
        await user_service.delete_user(created.id, actor)
    assert await users.get_by_id(created.id) is not None


@pytest.mark.asyncio
async def test_links_take_effect_in_permission_query(db, services):
    user_service, profile_service, users, _, profiles = services
    actor = await _make_admin(db)
    user = await user_service.create_user(
        UserCreate(name="V", email="f23-it-viewer@example.com", password=PASSWORD), actor)
    profile = await profile_service.create_profile(ProfileCreate(name="f23-it-link"), actor)
    analysis = await _make_analysis(db)

    assert await profiles.get_allowed_analysis_ids(user.id) == set()
    await profile_service.set_analyses(profile.id, [analysis], actor)
    await profile_service.set_users(profile.id, [user.id], actor)
    assert await profiles.get_allowed_analysis_ids(user.id) == {analysis}
    await user_service.set_profiles(user.id, [], actor)
    assert await profiles.get_allowed_analysis_ids(user.id) == set()

    with pytest.raises(InvalidReferenceError):
        from uuid import uuid4
        await profile_service.set_analyses(profile.id, [analysis, uuid4()], actor)
    assert [a.id for a in (await profile_service.get_profile(profile.id)).analyses] == [analysis]  # rollback


@pytest.mark.asyncio
async def test_last_admin_lock_and_protection(db, services):
    user_service, _, users, *_ = services
    # Ator é o único admin ativo com o prefixo; a verificação considera TODOS os admins do banco,
    # então isolamos: a proteção só dispara se o alvo for o único admin ativo.
    actor = await _make_admin(db)
    async with db.transaction() as tx:
        locked = await users.lock_active_admin_ids(tx)
    assert actor.id in locked

    others = [u for u in locked if u != actor.id]
    if others:
        pytest.skip("Há outros administradores ativos no banco; a corrida do último admin não é reproduzível")
    victim = await _make_admin(db, "f23-it-victim@example.com")
    await db.execute("UPDATE users SET is_blocked = true WHERE id = $1", actor.id)  # só a vítima resta
    with pytest.raises(LastAdminProtectedError):
        await user_service.set_blocked(victim.id, True, AuthenticatedUser(id=actor.id, name="x"))
