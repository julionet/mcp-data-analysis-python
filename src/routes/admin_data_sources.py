"""/admin/data-sources — F24 §4.4.2. Todas as rotas exigem administrador (`require_admin`).

`/types` e `/test-connection` são declaradas antes de `/{data_source_id}` (UUID) e não colidem.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from routes.admin_route import AdminRoute
from routes.openapi_docs import TAG_DATA_SOURCES, admin_responses
from routes.dependencies import get_data_source_admin_service
from schemas.admin import (
    ConnectionTestBody,
    ConnectionTestResult,
    DataSourceCreate,
    DataSourceDetail,
    DataSourceHasAnalysesError,
    DataSourceNameAlreadyExistsError,
    DataSourceNotFoundError,
    DataSourceSummary,
    DataSourceTypeInfo,
    DataSourceUpdate,
    InvalidConnectionConfigError,
    Page,
    UnsupportedDataSourceTypeError,
)
from schemas.auth import AuthenticatedUser
from security.admin_auth import get_current_user, require_admin
from services.data_source_admin_service import DataSourceAdminService

router = APIRouter(
    prefix="/admin/data-sources",
    tags=[TAG_DATA_SOURCES],
    dependencies=[Depends(require_admin)],
    route_class=AdminRoute,
)


@router.get("/types", response_model=list[DataSourceTypeInfo], summary='Listar tipos suportados', description='Tipos de banco aceitos e suas chaves de `connection_config` (obrigatórias, opcionais e alternativas).', responses=admin_responses())
async def list_types(service: DataSourceAdminService = Depends(get_data_source_admin_service)):
    return await service.list_types()


@router.post("/test-connection", response_model=ConnectionTestResult, summary='Testar conexão (prévio)', description='Testa uma configuração antes de salvar, sem gravá-la. Limite de 10 s. A falha de conexão é parte do resultado (200, `ok: false`), sem o texto do driver.', responses=admin_responses(InvalidConnectionConfigError, UnsupportedDataSourceTypeError))
async def test_connection_config(
    body: ConnectionTestBody,
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    return await service.test_config(body)


@router.get("", response_model=Page[DataSourceSummary], summary='Listar data sources', description='Lista paginada, com busca (`q`, no nome) e filtros por tipo e ativo.', responses=admin_responses())
async def list_data_sources(
    q: str | None = None,
    type: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    return await service.list_data_sources(q, type, is_active, limit, offset)


@router.post("", status_code=201, response_model=DataSourceDetail, summary='Criar data source', description='Valida a configuração do tipo, cifra a senha (Fernet) e salva. A senha nunca é devolvida.', responses=admin_responses(DataSourceNameAlreadyExistsError, InvalidConnectionConfigError, UnsupportedDataSourceTypeError))
async def create_data_source(
    body: DataSourceCreate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    return await service.create_data_source(body, actor)


@router.get("/{data_source_id}", response_model=DataSourceDetail, summary='Detalhar data source', description='Devolve o data source sem a senha (`has_password` indica se existe) e as analyses que o usam.', responses=admin_responses(DataSourceNotFoundError))
async def get_data_source(
    data_source_id: UUID,
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    return await service.get_data_source(data_source_id)


@router.patch("/{data_source_id}", response_model=DataSourceDetail, summary='Alterar data source', description='Altera apenas os campos enviados. `connection_config` é mesclado com o salvo (chave omitida permanece; `null` remove uma opcional; `password` só é recifrada se enviada). O `type` não é alterável. Editar a conexão ou `is_active` derruba o pool e invalida o cache das analyses da fonte.', responses=admin_responses(DataSourceNotFoundError, DataSourceNameAlreadyExistsError, InvalidConnectionConfigError))
async def update_data_source(
    data_source_id: UUID,
    body: DataSourceUpdate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    return await service.update_data_source(data_source_id, body, actor)


@router.delete("/{data_source_id}", status_code=204, summary='Excluir data source', description='Exclusão física, só sem analyses vinculadas; caso contrário responde 409 e o caminho é desativar (`is_active: false`).', responses=admin_responses(DataSourceNotFoundError, DataSourceHasAnalysesError))
async def delete_data_source(
    data_source_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    await service.delete_data_source(data_source_id, actor)
    return Response(status_code=204)


@router.post("/{data_source_id}/test-connection", response_model=ConnectionTestResult, summary='Testar conexão salva', description='Testa a conexão do data source já salvo (limite de 10 s). A falha é parte do resultado (200, `ok: false`).', responses=admin_responses(DataSourceNotFoundError))
async def test_saved_connection(
    data_source_id: UUID,
    service: DataSourceAdminService = Depends(get_data_source_admin_service),
):
    return await service.test_saved(data_source_id)
