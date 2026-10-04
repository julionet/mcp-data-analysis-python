"""ExecutionRepository — create() e get_all() sobre o adapter do Config DB."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from repositories.execution_repo import ExecutionRepository


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

    @pytest.mark.asyncio
    async def test_get_all_uses_execute_query(self):
        rows = [{"id": 1}, {"id": 2}]
        db = AsyncMock()
        db.execute_query.return_value = rows
        repo = ExecutionRepository(db)

        result = await repo.get_all(limit=5)

        assert result == rows
        query, params = db.execute_query.await_args.args
        assert "LIMIT $1" in query
        assert params == {"limit": 5}
