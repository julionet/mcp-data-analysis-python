"""Integração (Config DB real) — F24 §6.2.

Serviços e repositórios de data sources/analyses contra o banco de verdade: JSONB, transação
com rollback, cascatas, FKs, unicidade e o ciclo criar → executar → editar → executar. Pula
sozinho sem banco ou sem as tabelas/colunas da F12/F23. Tudo o que o teste cria tem o prefixo
`f24-it` e é removido no fim. O data source do ciclo aponta para o próprio Config DB.
"""

from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from adapters.postgresql import PostgreSQLAdapter
from config import settings
from repositories.analysis_repo import AnalysisRepository
from repositories.data_source_repo import DataSourceRepository
from repositories.execution_repo import ExecutionRepository
from repositories.profile_repo import ProfileRepository
from repositories.user_repo import UserRepository
from schemas.admin import (
    AnalysisCreate,
    AnalysisHasHistoryError,
    AnalysisNameAlreadyExistsError,
    AnalysisUpdate,
    DataSourceCreate,
    DataSourceHasAnalysesError,
    DataSourceNameAlreadyExistsError,
    DataSourceUpdate,
    InvalidReferenceError,
    StepInput,
    StepUpdate,
)
from schemas.auth import AuthenticatedUser
from security.crypto import decrypt_password
from services.analysis_admin_service import AnalysisAdminService
from services.analysis_service import AnalysisService
from services.audit_service import AuditService
from services.cache_backend import InMemoryBackend
from services.cache_service import CacheService
from services.data_source_admin_service import DataSourceAdminService
from services.volume_guard_service import VolumeGuardService

pytestmark = pytest.mark.integration  # F17: exige o Config DB (pulado sozinho sem banco)

SELF_CONFIG = dict(
    host=settings.postgres_config_host,
    port=settings.postgres_config_port,
    database=settings.postgres_config_database,
    user=settings.postgres_config_user,
    password=settings.postgres_config_password,
)


@pytest_asyncio.fixture
async def db():
    adapter = PostgreSQLAdapter({**SELF_CONFIG})
    try:
        await adapter.connect()
    except Exception:
        pytest.skip("Config DB indisponível")
    try:
        if await adapter.execute_query("SELECT to_regclass('public.access_tokens')", scalar=True) is None:
            pytest.skip("Tabelas do F12 ausentes — aplique database/schema.sql")
        yield adapter
    finally:
        await _cleanup(adapter)
        await adapter.disconnect()


async def _cleanup(db):
    await db.execute("DELETE FROM execution_history WHERE analysis_id IN (SELECT id FROM analyses WHERE name LIKE 'f24-it%')")
    await db.execute("DELETE FROM analyses WHERE name LIKE 'f24-it%'")
    await db.execute("DELETE FROM data_sources WHERE name LIKE 'f24-it%'")
    await db.execute("DELETE FROM profiles WHERE name LIKE 'f24-it%'")
    await db.execute("DELETE FROM users WHERE external_id LIKE 'f24-it%'")


class Pool:
    def __init__(self, target: AnalysisService | None = None) -> None:
        self.target, self.calls = target, []

    async def invalidate_data_source(self, ds_id) -> None:
        self.calls.append(ds_id)
        if self.target:
            await self.target.invalidate_data_source(ds_id)


@pytest_asyncio.fixture
async def ctx(db):
    users = UserRepository(db)
    analyses, sources, profiles = AnalysisRepository(db), DataSourceRepository(db), ProfileRepository(db)
    engine = AnalysisService(
        analyses, sources, VolumeGuardService(1000, 1000),
        CacheService(InMemoryBackend(100, 10), 1000, 1000), AuditService(ExecutionRepository(db)),
    )
    pool = Pool(engine)
    actor_id = await db.execute_query(
        "INSERT INTO users (name, external_id, password_hash, is_admin) "
        "VALUES ('Ator', 'f24-it-actor@example.com', 'x', true) RETURNING id", scalar=True)
    actor = AuthenticatedUser(id=actor_id, name="Ator")
    ctx = MagicMock()
    ctx.db, ctx.engine, ctx.pool, ctx.actor = db, engine, pool, actor
    ctx.ds = DataSourceAdminService(db, sources, pool, users)
    ctx.an = AnalysisAdminService(db, analyses, sources, profiles, users)
    yield ctx
    await engine.aclose()


async def _make_ds(ctx, name="f24-it-ds"):
    return await ctx.ds.create_data_source(
        DataSourceCreate(name=name, type="postgresql", connection_config=dict(SELF_CONFIG)), ctx.actor)


def _create(ds_id, name="f24-it-an", sql="SELECT :n::int AS valor", **kw):
    return AnalysisCreate(
        name=name, data_source_id=ds_id, parameters={"n": {"type": "integer", "required": True}},
        step=StepInput(sql=sql, params=["n"]), cache_frequency="daily", **kw)


@pytest.mark.asyncio
async def test_data_source_jsonb_roundtrip_encryption_and_unique(ctx, db):
    created = await _make_ds(ctx)
    assert created.has_password and "password" not in created.connection_config
    stored = await db.execute_query(
        "SELECT connection_config FROM data_sources WHERE id = $1", {"id": created.id})
    import json

    raw = stored[0]["connection_config"]
    raw = json.loads(raw) if isinstance(raw, str) else raw
    assert raw["password"] != SELF_CONFIG["password"]
    assert decrypt_password(raw["password"]) == SELF_CONFIG["password"]
    with pytest.raises(DataSourceNameAlreadyExistsError):
        await _make_ds(ctx)
    page = await ctx.ds.list_data_sources("f24-it", "postgresql", True, 10, 0)
    assert page.total == 1 and page.items[0].analyses_count == 0


@pytest.mark.asyncio
async def test_patch_merges_config_keeps_cipher(ctx, db):
    created = await _make_ds(ctx)
    before = await db.execute_query("SELECT connection_config FROM data_sources WHERE id = $1", {"id": created.id})
    updated = await ctx.ds.update_data_source(
        created.id, DataSourceUpdate(connection_config={"pool_min_size": 1, "pool_max_size": 3}), ctx.actor)
    assert updated.connection_config["pool_max_size"] == 3 and updated.connection_config["host"] == SELF_CONFIG["host"]
    after = await db.execute_query("SELECT connection_config FROM data_sources WHERE id = $1", {"id": created.id})
    import json

    load = lambda r: json.loads(r[0]["connection_config"]) if isinstance(r[0]["connection_config"], str) else r[0]["connection_config"]
    assert load(after)["password"] == load(before)["password"]
    assert ctx.pool.calls == [created.id]


@pytest.mark.asyncio
async def test_create_analysis_atomic_rollback_on_missing_profile(ctx, db):
    ds = await _make_ds(ctx)
    from uuid import uuid4

    with pytest.raises(InvalidReferenceError):
        await ctx.an.create_analysis(_create(ds.id, profile_ids=[uuid4()]), ctx.actor)
    assert not await db.execute_query("SELECT 1 FROM analyses WHERE name = 'f24-it-an'")
    assert not await db.execute_query(
        "SELECT 1 FROM analysis_steps s JOIN analyses a ON a.id = s.analysis_id WHERE a.name = 'f24-it-an'")


@pytest.mark.asyncio
async def test_analysis_crud_unique_cascade_and_fk(ctx, db):
    ds = await _make_ds(ctx)
    profile_id = await db.execute_query("INSERT INTO profiles (name) VALUES ('f24-it-p') RETURNING id", scalar=True)
    created = await ctx.an.create_analysis(_create(ds.id, profile_ids=[profile_id]), ctx.actor)
    assert created.step.params == ["n"] and [p.id for p in created.profiles] == [profile_id]
    assert created.parameters["n"]["type"] == "integer" and created.created_by == "f24-it-actor@example.com"
    with pytest.raises(AnalysisNameAlreadyExistsError):
        await ctx.an.create_analysis(_create(ds.id), ctx.actor)
    with pytest.raises(DataSourceHasAnalysesError):
        await ctx.ds.delete_data_source(ds.id, ctx.actor)

    page = await ctx.an.list_analyses("f24-it", ds.id, True, 10, 0)
    assert page.total == 1 and page.items[0].profiles_count == 1 and page.items[0].data_source_name == "f24-it-ds"

    await db.execute(
        "INSERT INTO execution_history (analysis_id, status) VALUES ($1, 'success')", created.id)
    with pytest.raises(AnalysisHasHistoryError):
        await ctx.an.delete_analysis(created.id, ctx.actor)
    await db.execute("DELETE FROM execution_history WHERE analysis_id = $1", created.id)
    await ctx.an.delete_analysis(created.id, ctx.actor)
    assert not await db.execute_query("SELECT 1 FROM analysis_steps WHERE analysis_id = $1", {"id": created.id})
    assert not await db.execute_query("SELECT 1 FROM profile_analyses WHERE analysis_id = $1", {"id": created.id})
    await ctx.ds.delete_data_source(ds.id, ctx.actor)


@pytest.mark.asyncio
async def test_full_cycle_create_execute_edit_execute_and_pool_refresh(ctx, db):
    ds = await _make_ds(ctx)
    analysis = await ctx.an.create_analysis(_create(ds.id), ctx.actor)

    first = await ctx.engine.execute(analysis.id, {"n": 7})
    assert first["status"] == "success" and first["data"] == [{"valor": 7}] and first["cached"] is False
    assert (await ctx.engine.execute(analysis.id, {"n": 7}))["cached"] is True
    assert ds.id in ctx.engine._adapters

    # editar o SQL nunca serve o resultado antigo do cache
    await ctx.an.update_analysis(
        analysis.id, AnalysisUpdate(step=StepUpdate(sql="SELECT :n::int * 2 AS valor")), ctx.actor)
    edited = await ctx.engine.execute(analysis.id, {"n": 7})
    assert edited["data"] == [{"valor": 14}] and edited["cached"] is False

    # invalidar o cache força nova consulta
    assert (await ctx.engine.execute(analysis.id, {"n": 7}))["cached"] is True
    await ctx.an.invalidate_cache(analysis.id, ctx.actor)
    assert (await ctx.engine.execute(analysis.id, {"n": 7}))["cached"] is False

    # editar a conexão derruba o pool; a execução seguinte recria o adapter
    old_adapter = ctx.engine._adapters[ds.id]
    await ctx.ds.update_data_source(ds.id, DataSourceUpdate(connection_config={"pool_min_size": 1, "pool_max_size": 2}), ctx.actor)
    assert ds.id not in ctx.engine._adapters
    after = await ctx.engine.execute(analysis.id, {"n": 1})
    assert after["status"] == "success" and after["cached"] is False
    assert ctx.engine._adapters[ds.id] is not old_adapter

    # desativar o data source: a execução falha com DATA_SOURCE_UNAVAILABLE
    await ctx.ds.update_data_source(ds.id, DataSourceUpdate(is_active=False), ctx.actor)
    off = await ctx.engine.execute(analysis.id, {"n": 1})
    assert off["status"] == "error" and off["error_code"] == "DATA_SOURCE_UNAVAILABLE"

    report = await ctx.an.validate(analysis.id)
    assert report.valid and [w.code for w in report.warnings] == ["data_source_inactive"]


@pytest.mark.asyncio
async def test_test_connection_against_real_database(ctx):
    ds = await _make_ds(ctx)
    result = await ctx.ds.test_saved(ds.id)
    assert result.ok is True and result.elapsed_ms >= 0
    bad = await ctx.ds.update_data_source(ds.id, DataSourceUpdate(connection_config={"password": "errada"}), ctx.actor)
    assert bad.has_password
    failed = await ctx.ds.test_saved(ds.id)
    assert failed.ok is False and failed.error_type
