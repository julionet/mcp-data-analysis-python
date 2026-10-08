"""/admin/analyses — F24 §4.5.1. Todas as rotas exigem administrador (`require_admin`)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from routes.admin_route import AdminRoute
from routes.dependencies import get_analysis_admin_service
from schemas.admin import (
    AnalysisCreate,
    AnalysisDetail,
    AnalysisSummary,
    AnalysisUpdate,
    InvalidateResult,
    Page,
    ProfileIdsBody,
    ValidationReport,
)
from schemas.auth import AuthenticatedUser
from security.admin_auth import get_current_user, require_admin
from services.analysis_admin_service import AnalysisAdminService

router = APIRouter(
    prefix="/admin/analyses",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
    route_class=AdminRoute,
)


@router.get("", response_model=Page[AnalysisSummary])
async def list_analyses(
    q: str | None = None,
    data_source_id: UUID | None = None,
    is_active: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: AnalysisAdminService = Depends(get_analysis_admin_service),
):
    return await service.list_analyses(q, data_source_id, is_active, limit, offset)


@router.post("", status_code=201, response_model=AnalysisDetail)
async def create_analysis(
    body: AnalysisCreate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: AnalysisAdminService = Depends(get_analysis_admin_service),
):
    return await service.create_analysis(body, actor)


@router.get("/{analysis_id}", response_model=AnalysisDetail)
async def get_analysis(
    analysis_id: UUID, service: AnalysisAdminService = Depends(get_analysis_admin_service)
):
    return await service.get_analysis(analysis_id)


@router.patch("/{analysis_id}", response_model=AnalysisDetail)
async def update_analysis(
    analysis_id: UUID,
    body: AnalysisUpdate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: AnalysisAdminService = Depends(get_analysis_admin_service),
):
    return await service.update_analysis(analysis_id, body, actor)


@router.delete("/{analysis_id}", status_code=204)
async def delete_analysis(
    analysis_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: AnalysisAdminService = Depends(get_analysis_admin_service),
):
    await service.delete_analysis(analysis_id, actor)
    return Response(status_code=204)


@router.put("/{analysis_id}/profiles", response_model=AnalysisDetail)
async def set_analysis_profiles(
    analysis_id: UUID,
    body: ProfileIdsBody,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: AnalysisAdminService = Depends(get_analysis_admin_service),
):
    return await service.set_profiles(analysis_id, body.profile_ids, actor)


@router.post("/{analysis_id}/validate", response_model=ValidationReport)
async def validate_analysis(
    analysis_id: UUID, service: AnalysisAdminService = Depends(get_analysis_admin_service)
):
    return await service.validate(analysis_id)


@router.post("/{analysis_id}/cache/invalidate", response_model=InvalidateResult)
async def invalidate_analysis_cache(
    analysis_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: AnalysisAdminService = Depends(get_analysis_admin_service),
):
    return await service.invalidate_cache(analysis_id, actor)
