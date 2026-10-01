"""Integração (Config DB real) — F12_AUTENTICACAO_PERFIS.md §6.2.

`AnalysisRepository.get_allowed_for_user()` (list_tools) e
`ProfileRepository.get_allowed_analysis_ids()` (revalidação do call_tool) precisam
concordar. Pula sozinho se as tabelas do F12 ainda não existem no banco
(aplicar database/migrations/f12_autenticacao.sql). Os dados criados são removidos no fim.
"""

import pytest
import pytest_asyncio

from adapters.postgresql import PostgreSQLAdapter
from config import settings
from repositories.analysis_repo import AnalysisRepository
from repositories.profile_repo import ProfileRepository


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
    await adapter.connect()
    try:
        has_tables = await adapter.execute_query("SELECT to_regclass('public.profile_analyses')", scalar=True)
        if has_tables is None:
            pytest.skip("Tabelas do F12 ausentes — aplique database/migrations/f12_autenticacao.sql")
        yield adapter
    finally:
        await adapter.disconnect()


async def _insert(db, sql: str, *args):
    async with db._pool.acquire() as conn:
        return await conn.fetchval(sql, *args)


@pytest.mark.asyncio
async def test_both_permission_queries_agree(db):
    created = {"users": [], "profiles": [], "analyses": [], "data_sources": []}
    try:
        ds = await _insert(
            db, "INSERT INTO data_sources (name, type, connection_config) VALUES ('f12-it-ds', 'postgresql', '{}') RETURNING id"
        )
        created["data_sources"].append(ds)
        analyses = {}
        for name, active in [("f12_it_ok", True), ("f12_it_inactive", False), ("f12_it_other", True), ("f12_it_inactive_profile", True)]:
            analyses[name] = await _insert(
                db,
                "INSERT INTO analyses (name, data_source_id, parameters, is_active) VALUES ($1, $2, '{}', $3) RETURNING id",
                name, ds, active,
            )
            created["analyses"].append(analyses[name])
        user = await _insert(db, "INSERT INTO users (name, external_id) VALUES ('IT', 'f12-it@example.com') RETURNING id")
        created["users"].append(user)
        active_profile = await _insert(db, "INSERT INTO profiles (name) VALUES ('f12-it-active') RETURNING id")
        inactive_profile = await _insert(
            db, "INSERT INTO profiles (name, is_active) VALUES ('f12-it-inactive', false) RETURNING id"
        )
        created["profiles"] += [active_profile, inactive_profile]
        for profile in (active_profile, inactive_profile):
            await _insert(db, "INSERT INTO user_profiles (user_id, profile_id) VALUES ($1, $2) RETURNING 1", user, profile)
        for name in ("f12_it_ok", "f12_it_inactive"):
            await _insert(db, "INSERT INTO profile_analyses (profile_id, analysis_id) VALUES ($1, $2) RETURNING 1", active_profile, analyses[name])
        await _insert(
            db, "INSERT INTO profile_analyses (profile_id, analysis_id) VALUES ($1, $2) RETURNING 1",
            inactive_profile, analyses["f12_it_inactive_profile"],
        )

        from_list = {a.id for a in await AnalysisRepository(db).get_allowed_for_user(user)}
        from_check = await ProfileRepository(db).get_allowed_analysis_ids(user)

        assert from_list == from_check == {analyses["f12_it_ok"]}
    finally:
        for table in ("users", "profiles", "analyses", "data_sources"):
            for row_id in created[table]:
                await _insert(db, f"DELETE FROM {table} WHERE id = $1 RETURNING 1", row_id)
