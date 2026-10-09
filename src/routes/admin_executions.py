"""/admin/executions — F25 §4.3. Somente leitura; todas as rotas exigem administrador."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from repositories.execution_repo import ExecutionFilters
from routes.admin_route import AdminRoute
from routes.openapi_docs import TAG_EXECUTIONS, admin_responses
from routes.dependencies import get_execution_admin_service
from schemas.admin import (
    ExecutionDetail,
    ExecutionErrorCode,
    ExecutionNotFoundError,
    ExecutionStats,
    ExecutionStatus,
    ExecutionSummary,
    InvalidParametersFilterError,
    InvalidPeriodError,
    Page,
)
from security.admin_auth import require_admin
from services.execution_admin_service import ExecutionAdminService, build_filters

router = APIRouter(
    prefix="/admin/executions",
    tags=[TAG_EXECUTIONS],
    dependencies=[Depends(require_admin)],
    route_class=AdminRoute,
)


def analysis_execution_filters(
    user_id: UUID | None = None,
    status: ExecutionStatus | None = None,
    error_code: ExecutionErrorCode | None = None,
    cached: bool | None = None,
    executed_from: datetime | None = Query(None, alias="from"),
    executed_to: datetime | None = Query(None, alias="to"),
    min_time_ms: int | None = Query(None, ge=0),
    parameters: str | None = None,
) -> ExecutionFilters:
    """Filtros sem `analysis_id` — usados também pelo atalho /admin/analyses/{id}/executions."""
    return build_filters(
        user_id=user_id, status=status, error_code=error_code, cached=cached,
        executed_from=executed_from, executed_to=executed_to,
        min_time_ms=min_time_ms, parameters=parameters,
    )


def execution_filters(
    analysis_id: UUID | None = None,
    filters: ExecutionFilters = Depends(analysis_execution_filters),
) -> ExecutionFilters:
    filters.analysis_id = analysis_id
    return filters


@router.get("", response_model=Page[ExecutionSummary], summary='Listar execuções', description='Lista paginada do histórico, mais recentes primeiro, com filtros por análise, usuário, status, `error_code`, cache, período (`from`/`to`; padrão: últimos 7 dias, máximo 366), tempo mínimo e `parameters` (JSON, igualdade de chave/valor).', responses=admin_responses(InvalidPeriodError, InvalidParametersFilterError))
async def list_executions(
    filters: ExecutionFilters = Depends(execution_filters),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: ExecutionAdminService = Depends(get_execution_admin_service),
):
    return await service.list_executions(filters, limit, offset)


# /stats antes de /{execution_id}: o literal precisa ser casado primeiro.
@router.get("/stats", response_model=ExecutionStats, summary='Estatísticas de execuções', description='Totais por status e `error_code`, taxa de cache hit, tempo (cache hit × miss: média, p95, máximo) e rankings de análises e usuários (`top`). Janela máxima definida pelo servidor.', responses=admin_responses(InvalidPeriodError))
async def execution_stats(
    executed_from: datetime | None = Query(None, alias="from"),
    executed_to: datetime | None = Query(None, alias="to"),
    analysis_id: UUID | None = None,
    user_id: UUID | None = None,
    top: int = Query(5, ge=1, le=20),
    service: ExecutionAdminService = Depends(get_execution_admin_service),
):
    return await service.get_stats(executed_from, executed_to, analysis_id, user_id, top)


@router.get("/{execution_id}", response_model=ExecutionDetail, summary='Detalhar execução', description='Devolve a execução com `error_message`.', responses=admin_responses(ExecutionNotFoundError))
async def get_execution(
    execution_id: UUID, service: ExecutionAdminService = Depends(get_execution_admin_service)
):
    return await service.get_execution(execution_id)
