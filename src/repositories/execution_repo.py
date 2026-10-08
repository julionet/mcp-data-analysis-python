"""Repository para execution_history — logs de execução de análises (F8)."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

_SELECT = """
    SELECT e.id, e.analysis_id, a.name AS analysis_name,
           e.user_id, u.name AS user_name, u.external_id AS user_email,
           e.status, e.error_code, e.cached, e.parameters,
           e.execution_time_ms, e.rows_affected, e.result_size_bytes, e.executed_at
"""
_FROM = """
      FROM execution_history e
      JOIN analyses a ON a.id = e.analysis_id
      LEFT JOIN users u ON u.id = e.user_id
"""
# Filtros opcionais $1–$9, na ordem de ExecutionFilters.as_params(): o adapter liga o dict por posição.
_WHERE = """
    WHERE ($1::uuid IS NULL OR e.analysis_id = $1)
      AND ($2::uuid IS NULL OR e.user_id = $2)
      AND ($3::text IS NULL OR e.status = $3)
      AND ($4::text IS NULL OR e.error_code = $4)
      AND ($5::boolean IS NULL OR e.cached = $5)
      AND ($6::timestamp IS NULL OR e.executed_at >= $6)
      AND ($7::timestamp IS NULL OR e.executed_at < $7)
      AND ($8::int IS NULL OR e.execution_time_ms >= $8)
      AND ($9::jsonb IS NULL OR e.parameters @> $9::jsonb)
"""
# /stats: $1 from (inclusivo), $2 to (exclusivo), $3 analysis_id, $4 user_id.
_PERIOD_WHERE = """
    WHERE e.executed_at >= $1 AND e.executed_at < $2
      AND ($3::uuid IS NULL OR e.analysis_id = $3)
      AND ($4::uuid IS NULL OR e.user_id = $4)
"""


def _status_counts() -> str:
    return ", ".join(
        f"COUNT(*) FILTER (WHERE e.status = '{status}') AS {status}"
        for status in ("success", "volume_exceeded", "error", "timeout")
    )


def _time_aggregates(prefix: str, cache_condition: str) -> str:
    """Contagem, média, p95 e máximo do tempo de execuções `success` (hit ou miss de cache)."""
    where = f"WHERE e.status = 'success' AND e.execution_time_ms IS NOT NULL AND {cache_condition}"
    return (
        f"COUNT(*) FILTER (WHERE e.status = 'success' AND {cache_condition}) AS {prefix}_count, "
        f"AVG(e.execution_time_ms) FILTER ({where}) AS {prefix}_avg, "
        f"percentile_cont(0.95) WITHIN GROUP (ORDER BY e.execution_time_ms) FILTER ({where}) AS {prefix}_p95, "
        f"MAX(e.execution_time_ms) FILTER ({where}) AS {prefix}_max"
    )


def _load_parameters(value: Any) -> dict:
    value = json.loads(value) if isinstance(value, str) else value
    return value if isinstance(value, dict) else {}


@dataclass
class ExecutionFilters:
    """Filtros de search/count (F25 §4.9). `executed_from` inclusivo, `executed_to` exclusivo,
    ambos naive (como a coluna `executed_at`); `parameters` é uma contenção JSONB."""

    analysis_id: UUID | None = None
    user_id: UUID | None = None
    status: str | None = None
    error_code: str | None = None
    cached: bool | None = None
    executed_from: datetime | None = None
    executed_to: datetime | None = None
    min_time_ms: int | None = None
    parameters: dict | None = None

    def as_params(self) -> dict:
        """Valores na ordem dos placeholders $1–$9 de `_WHERE`."""
        return {
            "analysis_id": self.analysis_id,
            "user_id": self.user_id,
            "status": self.status,
            "error_code": self.error_code,
            "cached": self.cached,
            "from": self.executed_from,
            "to": self.executed_to,
            "min_time_ms": self.min_time_ms,
            "parameters": json.dumps(self.parameters) if self.parameters is not None else None,
        }


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

    # ---- F25: consulta administrativa (somente leitura) ----

    async def search(self, filters: ExecutionFilters, limit: int, offset: int) -> list[dict]:
        """Página do histórico, da execução mais recente para a mais antiga. `user_*` vêm nulos
        em linhas pré-F12. O `parameters` volta decodificado (o asyncpg devolve JSONB como str)."""
        rows = await self.db.execute_query(
            f"{_SELECT} {_FROM} {_WHERE} ORDER BY e.executed_at DESC, e.id DESC LIMIT $10 OFFSET $11",
            {**filters.as_params(), "limit": limit, "offset": offset},
        )
        for row in rows:
            row["parameters"] = _load_parameters(row["parameters"])
        return rows

    async def count(self, filters: ExecutionFilters) -> int:
        """Total com os mesmos filtros (sem joins: não filtram nem multiplicam linhas)."""
        return await self.db.execute_query(
            f"SELECT COUNT(*) FROM execution_history e {_WHERE}", filters.as_params(), scalar=True
        )

    async def get_detail(self, execution_id: UUID) -> dict | None:
        """Uma execução, com `error_message`; None se não existe."""
        rows = await self.db.execute_query(
            f"{_SELECT}, e.error_message {_FROM} WHERE e.id = $1", {"id": execution_id}
        )
        if not rows:
            return None
        rows[0]["parameters"] = _load_parameters(rows[0]["parameters"])
        return rows[0]

    async def resolve_period(
        self, executed_from: datetime | None, executed_to: datetime | None, default_days: int
    ) -> tuple[datetime, datetime]:
        """Período efetivo do /stats. Os padrões usam o relógio do banco (LOCALTIMESTAMP, o mesmo
        que grava `executed_at` na sessão): sem `to` → agora; sem `from` → `to` − default_days."""
        rows = await self.db.execute_query(
            "SELECT COALESCE($2::timestamp, LOCALTIMESTAMP) AS period_to, "
            "COALESCE($1::timestamp, COALESCE($2::timestamp, LOCALTIMESTAMP) - $3::int * INTERVAL '1 day') "
            "AS period_from",
            {"from": executed_from, "to": executed_to, "days": default_days},
        )
        return rows[0]["period_from"], rows[0]["period_to"]

    async def stats(
        self,
        executed_from: datetime,
        executed_to: datetime,
        analysis_id: UUID | None,
        user_id: UUID | None,
        top: int,
    ) -> dict:
        """Agregados do período [from, to): totais, status, códigos de erro, cache, tempo
        (de `success`, separado em cache hit/miss) e os mais frequentes."""
        base = {"from": executed_from, "to": executed_to, "analysis_id": analysis_id, "user_id": user_id}
        agg = (
            await self.db.execute_query(
                f"""
                SELECT COUNT(*) AS total,
                       {_status_counts()},
                       {_time_aggregates("hit", "COALESCE(e.cached, false)")},
                       {_time_aggregates("miss", "NOT COALESCE(e.cached, false)")}
                  FROM execution_history e {_PERIOD_WHERE}
                """,
                base,
            )
        )[0]
        error_codes = await self.db.execute_query(
            f"SELECT e.error_code, COUNT(*) AS count FROM execution_history e {_PERIOD_WHERE} "
            "AND e.error_code IS NOT NULL GROUP BY e.error_code ORDER BY count DESC, e.error_code",
            base,
        )
        top_analyses = await self.db.execute_query(
            "SELECT e.analysis_id, a.name, COUNT(*) AS count FROM execution_history e "
            f"JOIN analyses a ON a.id = e.analysis_id {_PERIOD_WHERE} "
            "GROUP BY e.analysis_id, a.name ORDER BY count DESC, a.name, e.analysis_id LIMIT $5",
            {**base, "top": top},
        )
        top_users = await self.db.execute_query(
            "SELECT e.user_id, u.name, u.external_id AS email, COUNT(*) AS count FROM execution_history e "
            f"JOIN users u ON u.id = e.user_id {_PERIOD_WHERE} "
            "GROUP BY e.user_id, u.name, u.external_id ORDER BY count DESC, u.name, e.user_id LIMIT $5",
            {**base, "top": top},
        )
        return {"summary": agg, "error_codes": error_codes, "top_analyses": top_analyses, "top_users": top_users}
