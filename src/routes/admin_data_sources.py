"""/admin/data-sources — F24 §4.4.2. Todas as rotas exigem administrador (`require_admin`).

`/types` e `/test-connection` são declaradas antes de `/{data_source_id}` (UUID) e não colidem.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from routes.admin_route import AdminRoute
from routes.dependencies import get_data_source_admin_service
from schemas.admin import (
    ConnectionTestBody,
    ConnectionTestResult,
    DataSourceCreate,
    DataSourceDetail,
    DataSourceSummary,
    DataSourceTypeInfo,
    DataSourceUpdate,
    Page,
)
from schemas.auth import AuthenticatedUser
from security.admin_auth import get_current_user, require_admin
from services.data_source_admin_service import DataSourceAdminService

router = APIRouter(
    prefix="/admin/data-sources",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
    route_class=AdminRoute,
)


@router.get("/types", response_model=list[DataSourceTypeInfo])
async def list_types(service: DataSourceAdminService = Depends(get_data_source_admin_service)):
    return await service.list_types()


@router.post("/test-connection", response_model=ConnectionTestResult)
async def test_connection_config(
    body: ConnectionTestBody,
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    return await service.test_config(body)


@router.get("", response_model=Page[DataSourceSummary])
async def list_data_sources(
    q: str | None = None,
    type: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    return await service.list_data_sources(q, type, is_active, limit, offset)


@router.post("", status_code=201, response_model=DataSourceDetail)
async def create_data_source(
    body: DataSourceCreate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    return await service.create_data_source(body, actor)


@router.get("/{data_source_id}", response_model=DataSourceDetail)
async def get_data_source(
    data_source_id: UUID,
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    return await service.get_data_source(data_source_id)


@router.patch("/{data_source_id}", response_model=DataSourceDetail)
async def update_data_source(
    data_source_id: UUID,
    body: DataSourceUpdate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    return await service.update_data_source(data_source_id, body, actor)


@router.delete("/{data_source_id}", status_code=204)
async def delete_data_source(
    data_source_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    await service.delete_data_source(data_source_id, actor)
    return Response(status_code=204)


@router.post("/{data_source_id}/test-connection", response_model=ConnectionTestResult)
async def test_saved_connection(
    data_source_id: UUID,
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    return await service.test_saved(data_source_id)
