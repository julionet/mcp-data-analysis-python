"""ExecutionRepository — create() e get_all() sobre o adapter do Config DB."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from repositories.execution_repo import ExecutionRepository


class TestExecutionRepository:
    @pytest.mark.asyncio
    async def test_create_inserts_ten_columns_with_user_id(self):
        db = AsyncMock()
        repo = ExecutionRepository(db)
        analysis_id = uuid4()
        user_id = uuid4()

        await repo.create(
            analysis_id=analysis_id,
            parameters={"a": 1},
            status="success",
            execution_time_ms=12,
            rows_affected=3,
            result_size_bytes=100,
            error_message=None,
            result_location=None,
            cached=False,
            user_id=user_id,
        )

        query, *args = db.execute.await_args.args
        assert "analysis_version_id" not in query
        assert "user_id" in query and "$10" in query and "$11" not in query
        assert args == [analysis_id, '{"a": 1}', "success", 12, 3, 100, None, None, False, user_id]

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
