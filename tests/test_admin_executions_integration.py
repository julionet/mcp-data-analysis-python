"""Integração (Config DB real) — F25 §6.2.

Repositório e serviço de histórico contra o banco de verdade: JSONB e `@>`, LEFT JOIN com
`user_id` nulo, ordenação estável, fronteiras de `from`/`to`, `FILTER` e `percentile_cont` do
/stats e o ciclo executar (AuditService) → consultar. Pula sozinho sem banco ou sem as colunas
da F12/F14/F23. Tudo o que o teste cria tem o prefixo `f25-it` e é removido no fim.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from adapters.postgresql import PostgreSQLAdapter
from config import settings
from repositories.analysis_repo import AnalysisRepository
from repositories.execution_repo import ExecutionFilters, ExecutionRepository
from services.audit_service import AuditService
from services.execution_admin_service import ExecutionAdminService, build_filters

CONFIG = dict(
    host=settings.postgres_config_host,
    port=settings.postgres_config_port,
    database=settings.postgres_config_database,
    user=settings.postgres_config_user,
    password=settings.postgres_config_password,
)
# Janela fixa no passado distante: não se mistura com execuções reais do banco de desenvolvimento.
T0 = datetime(2001, 3, 1, 12, 0, 0)


@pytest_asyncio.fixture
async def db():
    adapter = PostgreSQLAdapter({**CONFIG})
    try:
        await adapter.connect()
    except Exception:
        pytest.skip("Config DB indisponível")
    try:
        missing = await adapter.execute_query(
            "SELECT 1 FROM information_schema.columns WHERE (table_name, column_name) IN "
            "(('users','is_admin'), ('execution_history','error_code')) HAVING COUNT(*) = 2",
        )
        if not missing:
            pytest.skip("Colunas users.is_admin / execution_history.error_code ausentes — aplique schema.sql")
        yield adapter
    finally:
        await _cleanup(adapter)
        await adapter.disconnect()


async def _cleanup(db):
    await db.execute("DELETE FROM execution_history WHERE analysis_id IN (SELECT id FROM analyses WHERE name LIKE 'f25-it%')")
    await db.execute("DELETE FROM analyses WHERE name LIKE 'f25-it%'")
    await db.execute("DELETE FROM data_sources WHERE name LIKE 'f25-it%'")
    await db.execute("DELETE FROM users WHERE external_id LIKE 'f25-it%'")


@pytest_asyncio.fixture
async def ctx(db):
    await _cleanup(db)
    ds_id = await db.execute_query(
        "INSERT INTO data_sources (name, type, connection_config) VALUES ('f25-it-ds', 'postgresql', '{}'::jsonb) RETURNING id",
        scalar=True,
    )
    a1 = await db.execute_query(
        "INSERT INTO analyses (name, data_source_id, parameters) VALUES ('f25-it-vendas', $1, '{}'::jsonb) RETURNING id",
        {"ds": ds_id}, scalar=True)
    a2 = await db.execute_query(
        "INSERT INTO analyses (name, data_source_id, parameters, is_active) VALUES ('f25-it-estoque', $1, '{}'::jsonb, false) RETURNING id",
        {"ds": ds_id}, scalar=True)
    user = await db.execute_query(
        "INSERT INTO users (name, external_id, password_hash) VALUES ('Maria IT', 'f25-it-maria@example.com', 'x') RETURNING id",
        scalar=True)
    repo = ExecutionRepository(db)
    c = MagicMock()
    c.db, c.repo, c.a1, c.a2, c.user = db, repo, a1, a2, user
    c.service = ExecutionAdminService(repo, AnalysisRepository(db))

    async def add(analysis_id, at, *, status="success", user_id=None, cached=False, time_ms=10,
                  params=None, error_code=None, error_message=None):
        """INSERT direto para controlar `executed_at` (o create() usa NOW())."""
        import json

        return await db.execute_query(
            "INSERT INTO execution_history (analysis_id, parameters, status, execution_time_ms, rows_affected, "
            "result_size_bytes, error_message, executed_at, cached, user_id, error_code) "
            "VALUES ($1, $2::jsonb, $3, $4, 1, 10, $5, $6, $7, $8, $9) RETURNING id",
            {"a": analysis_id, "p": json.dumps(params or {}), "s": status, "t": time_ms, "m": error_message,
             "at": at, "c": cached, "u": user_id, "e": error_code},
            scalar=True)

    c.add = add
    return c


def _only(ctx, **kw):
    """Filtros restritos às análises do teste (o banco pode ter outras execuções)."""
    return ExecutionFilters(**kw)


class TestSearchAgainstPostgres:
    @pytest.mark.asyncio
    async def test_filters_join_order_and_jsonb(self, ctx):
        await ctx.add(ctx.a1, T0, user_id=ctx.user, params={"regiao": "SP", "ano": 2025})
        await ctx.add(ctx.a1, T0 + timedelta(hours=1), params={"regiao": "RJ"}, status="error",
                      error_code="QUERY_FAILED", error_message="boom")
        await ctx.add(ctx.a2, T0 + timedelta(hours=2), params={"regiao": "SP", "ano": "2025"})

        rows = await ctx.repo.search(_only(ctx, executed_from=T0, executed_to=T0 + timedelta(days=1)), 50, 0)
        mine = [r for r in rows if r["analysis_name"].startswith("f25-it")]
        assert [r["analysis_name"] for r in mine] == ["f25-it-estoque", "f25-it-vendas", "f25-it-vendas"]
        legacy = mine[0]
        assert legacy["user_id"] is None and legacy["user_name"] is None  # LEFT JOIN, pré-F12
        assert mine[2]["user_email"] == "f25-it-maria@example.com"
        assert mine[2]["parameters"] == {"regiao": "SP", "ano": 2025}  # JSONB decodificado

        typed = await ctx.repo.search(_only(ctx, analysis_id=ctx.a1, parameters={"ano": 2025}), 50, 0)
        assert len(typed) == 1  # "2025" (texto) não casa com 2025 (número)
        assert await ctx.repo.count(_only(ctx, parameters={"regiao": "SP"}, executed_from=T0,
                                          executed_to=T0 + timedelta(days=1))) == 2
        by_code = await ctx.repo.search(_only(ctx, analysis_id=ctx.a1, error_code="QUERY_FAILED"), 50, 0)
        assert len(by_code) == 1

    @pytest.mark.asyncio
    async def test_from_inclusive_to_exclusive_and_stable_pagination(self, ctx):
        for _ in range(4):  # mesmo executed_at: o desempate por id mantém a paginação estável
            await ctx.add(ctx.a1, T0)
        await ctx.add(ctx.a1, T0 + timedelta(hours=1))
        f = _only(ctx, analysis_id=ctx.a1, executed_from=T0, executed_to=T0 + timedelta(hours=1))
        assert await ctx.repo.count(f) == 4  # `to` exclusivo
        seen = []
        for offset in range(0, 4, 2):
            seen += [r["id"] for r in await ctx.repo.search(f, 2, offset)]
        assert len(set(seen)) == 4 and seen == sorted(seen, reverse=True)
        assert await ctx.repo.count(_only(ctx, analysis_id=ctx.a1, executed_from=T0 + timedelta(hours=1))) == 1  # `from` inclusivo

    @pytest.mark.asyncio
    async def test_detail_has_error_message(self, ctx):
        eid = await ctx.add(ctx.a1, T0, status="error", error_code="QUERY_FAILED", error_message="coluna x")
        detail = await ctx.service.get_execution(eid)
        assert detail.error_message == "coluna x" and detail.analysis.name == "f25-it-vendas"


class TestStatsAgainstPostgres:
    @pytest.mark.asyncio
    async def test_aggregates_percentile_and_tops(self, ctx):
        for ms in (100, 200, 300, 400):
            await ctx.add(ctx.a1, T0 + timedelta(minutes=ms), user_id=ctx.user, time_ms=ms)
        await ctx.add(ctx.a1, T0, cached=True, time_ms=2)
        await ctx.add(ctx.a2, T0, status="timeout", error_code="QUERY_TIMEOUT", time_ms=9000)
        await ctx.add(ctx.a2, T0, status="volume_exceeded")

        stats = await ctx.service.get_stats(T0, T0 + timedelta(days=1), None, None, 5)
        assert stats.total == 7 - 0 and stats.by_status.success == 5
        assert (stats.by_status.timeout, stats.by_status.volume_exceeded, stats.by_status.error) == (1, 1, 0)
        assert stats.by_error_code == {"QUERY_TIMEOUT": 1}
        assert stats.cache.hits == 1 and stats.cache.hit_rate == pytest.approx(1 / 5)
        miss = stats.execution_time_ms["cache_miss"]
        assert (miss.count, miss.avg, miss.max) == (4, 250.0, 400)
        assert miss.p95 == pytest.approx(385.0)  # percentile_cont(0.95) de 100,200,300,400
        assert stats.execution_time_ms["cache_hit"].p95 == 2.0
        assert [(t.name, t.count) for t in stats.top_analyses if t.name.startswith("f25-it")] == [
            ("f25-it-vendas", 5), ("f25-it-estoque", 2)]
        assert any(u.email == "f25-it-maria@example.com" and u.count == 4 for u in stats.top_users)

    @pytest.mark.asyncio
    async def test_resolve_period_uses_database_clock(self, ctx):
        start, end = await ctx.repo.resolve_period(None, None, 7)
        assert end - start == timedelta(days=7)
        assert abs((datetime.now() - end).total_seconds()) < 3600 * 24  # relógio do banco ≈ agora
        start2, end2 = await ctx.repo.resolve_period(T0, None, 7)
        assert start2 == T0

    @pytest.mark.asyncio
    async def test_config_db_session_is_utc(self, ctx):
        """Premissa do fuso (F25 §4.3, decisão 11): `from`/`to` com offset viram UTC naive."""
        tz = await ctx.db.execute_query("SHOW timezone", scalar=True)
        assert tz in ("UTC", "Etc/UTC"), f"Config DB com fuso {tz}: revise a conversão de from/to"


class TestAuditCycle:
    @pytest.mark.asyncio
    async def test_executions_recorded_by_audit_service_are_listed(self, ctx):
        audit = AuditService(ctx.repo)
        await audit.log_execution(analysis_id=ctx.a1, parameters={"k": "v"}, status="success",
                                  execution_time_ms=5, cached=True, result={"data": [{"a": 1}, {"a": 2}]},
                                  user_id=ctx.user)
        await audit.log_execution(analysis_id=ctx.a1, parameters={}, status="error", execution_time_ms=7,
                                  error_message="falhou", cached=False, user_id=ctx.user,
                                  error_code="QUERY_FAILED")
        page = await ctx.service.list_by_analysis(ctx.a1, build_filters(), 50, 0)
        assert page.total == 2
        assert {i.status for i in page.items} == {"success", "error"}
        failed = next(i for i in page.items if i.status == "error")
        assert (await ctx.service.get_execution(failed.id)).error_message == "falhou"
        hit = next(i for i in page.items if i.cached)
        assert hit.parameters == {"k": "v"} and hit.rows_affected == 2
