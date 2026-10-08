"""Consulta administrativa ao histórico de execuções — F25 §4.5/§4.6. Somente leitura."""

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID


from repositories.analysis_repo import AnalysisRepository
from repositories.execution_repo import ExecutionFilters, ExecutionRepository
from schemas.admin import (
    AdminAnalysisNotFoundError,
    CacheStats,
    ExecutionAnalysisRef,
    ExecutionDetail,
    ExecutionNotFoundError,
    ExecutionStats,
    ExecutionSummary,
    ExecutionTopAnalysis,
    ExecutionTopUser,
    ExecutionUserRef,
    InvalidParametersFilterError,
    InvalidPeriodError,
    Page,
    StatusCounts,
    TimeStats,
)

STATS_DEFAULT_DAYS = 7
STATS_MAX_DAYS = 366
PARAMETERS_FILTER_MAX_CHARS = 1000


def to_naive_utc(value: datetime | None) -> datetime | None:
    """`executed_at` é TIMESTAMP sem fuso (UTC no compose): datas com offset viram UTC naive;
    datas sem offset são comparadas como estão (F25 §4.3, decisão 11)."""
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def parse_parameters_filter(raw: str | None) -> dict | None:
    """`?parameters=` precisa ser um objeto JSON não vazio de até 1.000 caracteres. O valor
    recebido nunca entra na mensagem de erro (pode ser dado sensível)."""
    if raw is None:
        return None
    message = "O filtro 'parameters' deve ser um objeto JSON não vazio, ex.: {\"regiao\":\"SP\"}."
    if len(raw) > PARAMETERS_FILTER_MAX_CHARS:
        raise InvalidParametersFilterError(
            f"O filtro 'parameters' passa de {PARAMETERS_FILTER_MAX_CHARS} caracteres."
        )
    try:
        value = json.loads(raw)
    except ValueError:
        raise InvalidParametersFilterError(message) from None
    if not isinstance(value, dict) or not value:
        raise InvalidParametersFilterError(message)
    return value


def build_filters(
    *,
    analysis_id=None,
    user_id=None,
    status=None,
    error_code=None,
    cached=None,
    executed_from: datetime | None = None,
    executed_to: datetime | None = None,
    min_time_ms=None,
    parameters: str | None = None,
) -> ExecutionFilters:
    """Valida e normaliza os filtros da querystring (usada como dependência pelas rotas)."""
    executed_from, executed_to = to_naive_utc(executed_from), to_naive_utc(executed_to)
    if executed_from is not None and executed_to is not None and executed_from >= executed_to:
        raise InvalidPeriodError("'from' deve ser anterior a 'to'.")
    return ExecutionFilters(
        analysis_id=analysis_id,
        user_id=user_id,
        status=status,
        error_code=error_code,
        cached=cached,
        executed_from=executed_from,
        executed_to=executed_to,
        min_time_ms=min_time_ms,
        parameters=parse_parameters_filter(parameters),
    )


def _summary_fields(row: dict) -> dict:
    user = (
        ExecutionUserRef(id=row["user_id"], name=row["user_name"], email=row["user_email"])
        if row["user_id"] is not None
        else None
    )
    return dict(
        id=row["id"],
        analysis=ExecutionAnalysisRef(id=row["analysis_id"], name=row["analysis_name"]),
        user=user,
        status=row["status"],
        error_code=row["error_code"],
        cached=bool(row["cached"]),
        parameters=row["parameters"] or {},
        execution_time_ms=row["execution_time_ms"],
        rows_affected=row["rows_affected"],
        result_size_bytes=row["result_size_bytes"],
        executed_at=row["executed_at"],
    )


def _time_stats(summary: dict, prefix: str) -> TimeStats:
    avg, p95 = summary[f"{prefix}_avg"], summary[f"{prefix}_p95"]
    return TimeStats(
        count=summary[f"{prefix}_count"],
        avg=float(avg) if avg is not None else None,
        p95=float(p95) if p95 is not None else None,
        max=summary[f"{prefix}_max"],
    )


class ExecutionAdminService:
    def __init__(self, repo: ExecutionRepository, analyses: AnalysisRepository) -> None:
        self._repo = repo
        self._analyses = analyses

    async def list_executions(self, filters: ExecutionFilters, limit: int, offset: int) -> Page[ExecutionSummary]:
        rows = await self._repo.search(filters, limit, offset)
        total = await self._repo.count(filters)
        items = [ExecutionSummary(**_summary_fields(r)) for r in rows]
        return Page(items=items, total=total, limit=limit, offset=offset)

    async def list_by_analysis(
        self, analysis_id: UUID, filters: ExecutionFilters, limit: int, offset: int
    ) -> Page[ExecutionSummary]:
        """Atalho por análise; aceita análise inativa (get_admin_row não filtra is_active)."""
        if await self._analyses.get_admin_row(analysis_id) is None:
            raise AdminAnalysisNotFoundError()
        filters.analysis_id = analysis_id
        return await self.list_executions(filters, limit, offset)

    async def get_execution(self, execution_id: UUID) -> ExecutionDetail:
        row = await self._repo.get_detail(execution_id)
        if row is None:
            raise ExecutionNotFoundError()
        return ExecutionDetail(**_summary_fields(row), error_message=row["error_message"])

    async def get_stats(
        self,
        executed_from: datetime | None,
        executed_to: datetime | None,
        analysis_id: UUID | None,
        user_id: UUID | None,
        top: int,
    ) -> ExecutionStats:
        executed_from, executed_to = to_naive_utc(executed_from), to_naive_utc(executed_to)
        period_from, period_to = await self._repo.resolve_period(executed_from, executed_to, STATS_DEFAULT_DAYS)
        if period_from >= period_to:
            raise InvalidPeriodError("'from' deve ser anterior a 'to'.")
        if period_to - period_from > timedelta(days=STATS_MAX_DAYS):
            raise InvalidPeriodError(f"A janela das estatísticas é de no máximo {STATS_MAX_DAYS} dias.")
        data = await self._repo.stats(period_from, period_to, analysis_id, user_id, top)
        summary = data["summary"]
        success, hits = summary["success"], summary["hit_count"]
        return ExecutionStats(
            period={"from": period_from, "to": period_to},
            total=summary["total"],
            by_status=StatusCounts(
                success=success,
                volume_exceeded=summary["volume_exceeded"],
                error=summary["error"],
                timeout=summary["timeout"],
            ),
            by_error_code={r["error_code"]: r["count"] for r in data["error_codes"]},
            cache=CacheStats(hits=hits, success=success, hit_rate=hits / success if success else None),
            execution_time_ms={
                "cache_hit": _time_stats(summary, "hit"),
                "cache_miss": _time_stats(summary, "miss"),
            },
            top_analyses=[ExecutionTopAnalysis(**r) for r in data["top_analyses"]],
            top_users=[ExecutionTopUser(**r) for r in data["top_users"]],
        )
