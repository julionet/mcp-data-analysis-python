"""ExecutionRepository — create() (F8/F12/F14) e consulta administrativa (F25) sobre o adapter do Config DB."""

from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from repositories.execution_repo import ExecutionFilters, ExecutionRepository


class TestExecutionRepository:
    @pytest.mark.asyncio
    async def test_create_inserts_eleven_columns_with_user_id_and_error_code(self):
        db = AsyncMock()
        repo = ExecutionRepository(db)
        analysis_id = uuid4()
        user_id = uuid4()

        await repo.create(
            analysis_id=analysis_id,
            parameters={"a": 1},
            status="timeout",
            execution_time_ms=12,
            rows_affected=3,
            result_size_bytes=100,
            error_message="estourou",
            result_location=None,
            cached=False,
            user_id=user_id,
            error_code="QUERY_TIMEOUT",
        )

        query, *args = db.execute.await_args.args
        assert "analysis_version_id" not in query
        assert "user_id, error_code" in query and "$11" in query and "$12" not in query
        assert args == [
            analysis_id, '{"a": 1}', "timeout", 12, 3, 100, "estourou", None, False, user_id, "QUERY_TIMEOUT",
        ]

    @pytest.mark.asyncio
    async def test_create_without_error_code_writes_none(self):
        """Sem erro (ou chamadores pré-F14): error_code fica NULL."""
        db = AsyncMock()

        await ExecutionRepository(db).create(
            analysis_id=uuid4(), parameters={}, status="success", execution_time_ms=1,
            rows_affected=0, result_size_bytes=2, error_message=None, result_location=None, cached=False,
        )

        _, *args = db.execute.await_args.args
        assert args[-1] is None

    def test_insert_columns_match_schema_sql(self):
        """O INSERT e o schema.sql falam das mesmas colunas: esquecer o ALTER TABLE num banco
        existente faz o INSERT falhar (e o AuditService engole o erro — histórico perdido)."""
        import re
        from pathlib import Path

        import repositories.execution_repo as module

        schema = (Path(module.__file__).parents[1] / "database" / "schema.sql").read_text(encoding="utf-8")
        table = re.search(r"CREATE TABLE execution_history \((.*?)\n\);", schema, re.S).group(1)
        schema_columns = {
            line.split()[0] for line in table.splitlines() if line.strip() and not line.strip().startswith("--")
        }

        source = Path(module.__file__).read_text(encoding="utf-8")
        insert_block = re.search(r"INSERT INTO execution_history\s*\((.*?)\)\s*VALUES", source, re.S).group(1)
        insert_columns = {c.strip() for c in insert_block.split(",")}

        assert insert_columns <= schema_columns

    @pytest.mark.asyncio
    async def test_create_without_user_id_writes_none(self):
        """Linhas legadas/pré-F12 (sem usuário) continuam sendo gravadas."""
        db = AsyncMock()
        repo = ExecutionRepository(db)

        await repo.create(
            analysis_id=uuid4(),
            parameters={},
            status="success",
            execution_time_ms=1,
            rows_affected=0,
            result_size_bytes=2,
            error_message=None,
            result_location=None,
            cached=False,
        )

        _, *args = db.execute.await_args.args
        assert args[-1] is None

    def test_get_all_was_replaced_by_search(self):
        assert not hasattr(ExecutionRepository, "get_all")


class TestExecutionQueries:
    """F25: SQL e ordem dos valores ligados (o adapter liga o dict por posição, `$1…$n`)."""

    @pytest.mark.asyncio
    async def test_search_without_filters_binds_nulls_then_limit_offset(self):
        db = AsyncMock()
        db.execute_query.return_value = [{"parameters": '{"a": 1}'}, {"parameters": None}]

        rows = await ExecutionRepository(db).search(ExecutionFilters(), 50, 100)

        query, params = db.execute_query.await_args.args
        assert list(params.values()) == [None] * 9 + [50, 100]
        assert "ORDER BY e.executed_at DESC, e.id DESC LIMIT $10 OFFSET $11" in query
        assert "LEFT JOIN users u" in query and "JOIN analyses a" in query
        assert "error_message" not in query and "password" not in query and "token" not in query
        assert [r["parameters"] for r in rows] == [{"a": 1}, {}]

    @pytest.mark.asyncio
    async def test_search_binds_every_filter_in_placeholder_order(self):
        db = AsyncMock()
        db.execute_query.return_value = []
        aid, uid = uuid4(), uuid4()
        start, end = datetime(2026, 10, 1), datetime(2026, 10, 2)
        filters = ExecutionFilters(aid, uid, "error", "QUERY_FAILED", False, start, end, 500, {"regiao": "SP"})

        await ExecutionRepository(db).search(filters, 10, 0)

        query, params = db.execute_query.await_args.args
        assert list(params.values()) == [
            aid, uid, "error", "QUERY_FAILED", False, start, end, 500, '{"regiao": "SP"}', 10, 0,
        ]
        for i, fragment in enumerate(
            ["e.analysis_id = $1", "e.user_id = $2", "e.status = $3", "e.error_code = $4", "e.cached = $5",
             "e.executed_at >= $6", "e.executed_at < $7", "e.execution_time_ms >= $8", "e.parameters @> $9::jsonb"],
            start=1,
        ):
            assert fragment in query, i

    @pytest.mark.asyncio
    async def test_count_uses_same_filters_without_joins(self):
        db = AsyncMock()
        db.execute_query.return_value = 7

        total = await ExecutionRepository(db).count(ExecutionFilters(status="error"))

        query, params = db.execute_query.await_args.args
        assert total == 7 and db.execute_query.await_args.kwargs == {"scalar": True}
        assert "JOIN" not in query and "FROM execution_history e" in query
        assert list(params.values())[:3] == [None, None, "error"] and len(params) == 9

    @pytest.mark.asyncio
    async def test_get_detail_includes_error_message_and_none_when_missing(self):
        db = AsyncMock()
        eid = uuid4()
        db.execute_query.return_value = [{"id": eid, "parameters": '{"x": 2}', "error_message": "boom"}]

        row = await ExecutionRepository(db).get_detail(eid)

        query, params = db.execute_query.await_args.args
        assert "e.error_message" in query and "WHERE e.id = $1" in query and params == {"id": eid}
        assert row["parameters"] == {"x": 2} and row["error_message"] == "boom"
        db.execute_query.return_value = []
        assert await ExecutionRepository(db).get_detail(eid) is None

    @pytest.mark.asyncio
    async def test_resolve_period_uses_database_clock(self):
        db = AsyncMock()
        start, end = datetime(2026, 10, 1), datetime(2026, 10, 8)
        db.execute_query.return_value = [{"period_from": start, "period_to": end}]

        result = await ExecutionRepository(db).resolve_period(None, None, 7)

        query, params = db.execute_query.await_args.args
        assert result == (start, end) and "LOCALTIMESTAMP" in query
        assert list(params.values()) == [None, None, 7]

    @pytest.mark.asyncio
    async def test_stats_runs_four_read_only_queries_with_period_bounds(self):
        db = AsyncMock()
        db.execute_query.side_effect = [[{"total": 0}], [], [], []]
        start, end, aid = datetime(2026, 10, 1), datetime(2026, 10, 8), uuid4()

        data = await ExecutionRepository(db).stats(start, end, aid, None, 5)

        queries = [c.args[0] for c in db.execute_query.await_args_list]
        assert len(queries) == 4 and set(data) == {"summary", "error_codes", "top_analyses", "top_users"}
        assert all(q.lstrip().upper().startswith("SELECT") for q in queries)
        assert "percentile_cont(0.95) WITHIN GROUP" in queries[0] and "FILTER" in queries[0]
        assert all("e.executed_at >= $1 AND e.executed_at < $2" in q for q in queries)
        first_params = db.execute_query.await_args_list[0].args[1]
        assert list(first_params.values()) == [start, end, aid, None]
        assert list(db.execute_query.await_args_list[2].args[1].values()) == [start, end, aid, None, 5]
        assert "e.user_id IS NOT NULL" not in queries[3] and "JOIN users u" in queries[3]
