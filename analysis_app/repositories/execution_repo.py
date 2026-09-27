"""Repository para execution_history — logs de execução de análises (F8)."""

import json
from uuid import UUID


class ExecutionRepository:
    """Responsável por persistir execuções em execution_history."""

    def __init__(self, db) -> None:
        self.db = db

    async def create(
        self,
        analysis_id: UUID,
        analysis_version_id: UUID | None,
        parameters: dict,
        status: str,
        execution_time_ms: int,
        rows_affected: int | None,
        result_size_bytes: int | None,
        error_message: str | None,
        result_location: str | None,
        cached: bool,
    ) -> None:
        """Grava 1 linha em execution_history."""
        await self.db.execute(
            """
            INSERT INTO execution_history
                (analysis_id, analysis_version_id, parameters, status,
                 execution_time_ms, rows_affected, result_size_bytes,
                 error_message, result_location, cached)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            analysis_id,
            analysis_version_id,
            json.dumps(parameters, default=str),
            status,
            execution_time_ms,
            rows_affected,
            result_size_bytes,
            error_message,
            result_location,
            cached,
        )

    async def get_all(self, limit: int = 100) -> list[dict]:
        """Retorna histórico de execuções (sem exposição via MCP nesta feature)."""
        rows = await self.db.fetch(
            "SELECT * FROM execution_history ORDER BY executed_at DESC LIMIT $1",
            limit,
        )
        return [dict(row) for row in rows]
