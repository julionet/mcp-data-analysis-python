"""/admin/analyses — F24 §4.5.1. Todas as rotas exigem administrador (`require_admin`)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from routes.admin_route import AdminRoute
from routes.openapi_docs import TAG_ANALYSES, admin_responses
from repositories.execution_repo import ExecutionFilters
from routes.admin_executions import analysis_execution_filters
from routes.dependencies import get_analysis_admin_service, get_execution_admin_service
from schemas.admin import (
    AdminAnalysisNotFoundError,
    AnalysisCreate,
    AnalysisDetail,
    AnalysisHasHistoryError,
    AnalysisNameAlreadyExistsError,
    AnalysisSummary,
    AnalysisUpdate,
    ExecutionSummary,
    InvalidAnalysisDefinitionError,
    InvalidParametersFilterError,
    InvalidPeriodError,
    InvalidReferenceError,
    InvalidateResult,
    Page,
    ProfileIdsBody,
    ValidationReport,
)
from schemas.auth import AuthenticatedUser
from security.admin_auth import get_current_user, require_admin
from services.analysis_admin_service import AnalysisAdminService
from services.execution_admin_service import ExecutionAdminService

router = APIRouter(
    prefix="/admin/analyses",
    tags=[TAG_ANALYSES],
    dependencies=[Depends(require_admin)],
    route_class=AdminRoute,
)


@router.get("", response_model=Page[AnalysisSummary], summary='Listar analyses', description='Lista paginada, com busca (`q`, nome ou descrição) e filtros por data source e ativo.', responses=admin_responses())
async def list_analyses(
    q: str | None = None,
    data_source_id: UUID | None = None,
    is_active: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: AnalysisAdminService = Depends(get_analysis_admin_service),
):
    return await service.list_analyses(q, data_source_id, is_active, limit, offset)


@router.post("", status_code=201, response_model=AnalysisDetail, summary='Criar análise', description='Cria a análise, a query (step) e os perfis numa transação, após validação estática da definição (parâmetros, SQL somente SELECT, `cache_frequency`).', responses=admin_responses(AnalysisNameAlreadyExistsError, InvalidReferenceError, InvalidAnalysisDefinitionError))
async def create_analysis(
    body: AnalysisCreate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: AnalysisAdminService = Depends(get_analysis_admin_service),
):
    return await service.create_analysis(body, actor)


@router.get("/{analysis_id}", response_model=AnalysisDetail, summary='Detalhar análise', description='Devolve a análise com parâmetros, query e perfis.', responses=admin_responses(AdminAnalysisNotFoundError))
async def get_analysis(
    analysis_id: UUID, service: AnalysisAdminService = Depends(get_analysis_admin_service)
):
    return await service.get_analysis(analysis_id)


@router.patch("/{analysis_id}", response_model=AnalysisDetail, summary='Alterar análise', description='Altera apenas os campos enviados. `parameters` substitui o objeto inteiro; `step` mescla `sql`/`params`. A definição só é revalidada quando o PATCH a toca; alterações de definição atualizam `updated_at` (invalida o cache).', responses=admin_responses(AdminAnalysisNotFoundError, AnalysisNameAlreadyExistsError, InvalidReferenceError, InvalidAnalysisDefinitionError))
async def update_analysis(
    analysis_id: UUID,
    body: AnalysisUpdate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: AnalysisAdminService = Depends(get_analysis_admin_service),
):
    return await service.update_analysis(analysis_id, body, actor)


@router.delete("/{analysis_id}", status_code=204, summary='Excluir análise', description='Exclusão física, só sem histórico de execuções; com histórico responde 409 e o caminho é desativar (`is_active: false`).', responses=admin_responses(AdminAnalysisNotFoundError, AnalysisHasHistoryError))
async def delete_analysis(
    analysis_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: AnalysisAdminService = Depends(get_analysis_admin_service),
):
    await service.delete_analysis(analysis_id, actor)
    return Response(status_code=204)


@router.put("/{analysis_id}/profiles", response_model=AnalysisDetail, summary='Definir perfis da análise', description='Substitui o conjunto de perfis que podem executar a análise.', responses=admin_responses(AdminAnalysisNotFoundError, InvalidReferenceError))
async def set_analysis_profiles(
    analysis_id: UUID,
    body: ProfileIdsBody,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: AnalysisAdminService = Depends(get_analysis_admin_service),
):
    return await service.set_profiles(analysis_id, body.profile_ids, actor)


@router.post("/{analysis_id}/validate", response_model=ValidationReport, summary='Validar definição', description='Validação apenas estática da definição salva (não executa a query nem acessa o data source). Devolve erros e avisos.', responses=admin_responses(AdminAnalysisNotFoundError))
async def validate_analysis(
    analysis_id: UUID, service: AnalysisAdminService = Depends(get_analysis_admin_service)
):
    return await service.validate(analysis_id)


@router.post("/{analysis_id}/cache/invalidate", response_model=InvalidateResult, summary='Invalidar cache', description='Invalida o cache da análise atualizando `updated_at = NOW()`.', responses=admin_responses(AdminAnalysisNotFoundError))
async def invalidate_analysis_cache(
    analysis_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: AnalysisAdminService = Depends(get_analysis_admin_service),
):
    return await service.invalidate_cache(analysis_id, actor)


@router.get("/{analysis_id}/executions", response_model=Page[ExecutionSummary], summary='Histórico da análise', description='Atalho de `GET /admin/executions` já filtrado pela análise (aceita também as análises inativas). Mesmos filtros, sem `analysis_id`.', responses=admin_responses(AdminAnalysisNotFoundError, InvalidPeriodError, InvalidParametersFilterError))
async def list_analysis_executions(
    analysis_id: UUID,
    filters: ExecutionFilters = Depends(analysis_execution_filters),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: ExecutionAdminService = Depends(get_execution_admin_service),
):
    """F25: atalho do histórico por análise (404 se a análise não existe; inativa é aceita)."""
    return await service.list_by_analysis(analysis_id, filters, limit, offset)
