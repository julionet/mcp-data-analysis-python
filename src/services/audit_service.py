"""Audit Service — logs de execução em execution_history (F8).

Responsável por registrar cada execução de análise que chega a resolver o ID,
identificando o usuário autenticado (F12, `user_id`) mas não o cliente MCP.
"""

import json
import logging
from uuid import UUID

from repositories.execution_repo import ExecutionRepository

logger = logging.getLogger(__name__)


class AuditService:
    """Registra execuções em execution_history — suporta qualquer status
    (success, volume_exceeded, error, timeout — este último desde a F14)."""

    def __init__(self, execution_repo: ExecutionRepository) -> None:
        self.execution_repo = execution_repo

    async def log_execution(
        self,
        analysis_id: UUID,
        parameters: dict,
        status: str,  # "success" | "volume_exceeded" | "error" | "timeout"
        execution_time_ms: int,
        cached: bool,
        result: dict | None = None,
        error_message: str | None = None,
        user_id: UUID | None = None,
        error_code: str | None = None,
    ) -> None:
        """Grava 1 linha em execution_history. Nunca propaga exceção — uma
        falha de auditoria não pode derrubar a resposta ao cliente MCP."""
        rows_affected = None
        result_size_bytes = None

        if status == "success" and result is not None:
            data = result.get("data", [])
            rows_affected = len(data)
            result_size_bytes = len(json.dumps(data, default=str).encode("utf-8"))
        elif status == "volume_exceeded" and result is not None:
            estimativa = result.get("estimativa", {})
            rows_affected = estimativa.get("linhas")
            tamanho_kb = estimativa.get("tamanho_estimado_kb")
            result_size_bytes = int(tamanho_kb * 1024) if tamanho_kb is not None else None

        try:
            await self.execution_repo.create(
                analysis_id=analysis_id,
                parameters=parameters,
                status=status,
                execution_time_ms=execution_time_ms,
                rows_affected=rows_affected,
                result_size_bytes=result_size_bytes,
                error_message=error_message if status in ("error", "timeout") else None,
                result_location=None,
                cached=cached,
                user_id=user_id,
                error_code=error_code if status in ("error", "timeout") else None,
            )
        except Exception:
            logger.exception("Falha ao gravar execution_history (análise '%s')", analysis_id)
