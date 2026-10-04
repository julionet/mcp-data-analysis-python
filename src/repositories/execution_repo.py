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
        parameters: dict,
        status: str,
        execution_time_ms: int,
        rows_affected: int | None,
        result_size_bytes: int | None,
        error_message: str | None,
        result_location: str | None,
        cached: bool,
        user_id: UUID | None = None,
        error_code: str | None = None,
    ) -> None:
        """Grava 1 linha em execution_history. `user_id` (F12): quem executou; None em
        linhas legadas/pré-F12. `error_code` (F14): código estável do erro (None se não houve)."""
        await self.db.execute(
            """
            INSERT INTO execution_history
                (analysis_id, parameters, status,
                 execution_time_ms, rows_affected, result_size_bytes,
                 error_message, result_location, cached, user_id, error_code)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            analysis_id,
            json.dumps(parameters, default=str),
            status,
            execution_time_ms,
            rows_affected,
            result_size_bytes,
            error_message,
            result_location,
            cached,
            user_id,
            error_code,
        )

    async def get_all(self, limit: int = 100) -> list[dict]:
        """Retorna histórico de execuções (sem exposição via MCP nesta feature)."""
        # execute_query() do adapter já devolve list[dict] — não há fetch() no adapter.
        return await self.db.execute_query(
            "SELECT * FROM execution_history ORDER BY executed_at DESC LIMIT $1",
            {"limit": limit},
        )
