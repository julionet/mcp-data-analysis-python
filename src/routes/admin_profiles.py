"""/admin/profiles — F23 §4.4.3. Todas as rotas exigem administrador (`require_admin`)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from routes.admin_route import AdminRoute
from routes.openapi_docs import TAG_PROFILES, admin_responses
from routes.dependencies import get_profile_admin_service
from schemas.admin import (
    AnalysisIdsBody,
    InvalidReferenceError,
    Page,
    ProfileCreate,
    ProfileDetail,
    ProfileNameAlreadyExistsError,
    ProfileNotFoundError,
    ProfileSummary,
    ProfileUpdate,
    UserIdsBody,
)
from schemas.auth import AuthenticatedUser
from security.admin_auth import get_current_user, require_admin
from services.profile_admin_service import ProfileAdminService

router = APIRouter(
    prefix="/admin/profiles",
    tags=[TAG_PROFILES],
    dependencies=[Depends(require_admin)],
    route_class=AdminRoute,
)


@router.get("", response_model=Page[ProfileSummary], summary='Listar perfis', description='Lista paginada, com busca textual (`q`, nome ou descrição) e filtro por ativo, com contagem de usuários e analyses.', responses=admin_responses())
async def list_profiles(
    q: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: ProfileAdminService = Depends(get_profile_admin_service),
):
    return await service.list_profiles(q, is_active, limit, offset)


@router.post("", status_code=201, response_model=ProfileDetail, summary='Criar perfil', description='Cria um perfil (nome único).', responses=admin_responses(ProfileNameAlreadyExistsError))
async def create_profile(
    body: ProfileCreate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: ProfileAdminService = Depends(get_profile_admin_service),
):
    return await service.create_profile(body, actor)


@router.get("/{profile_id}", response_model=ProfileDetail, summary='Detalhar perfil', description='Devolve o perfil com os usuários e as analyses vinculados.', responses=admin_responses(ProfileNotFoundError))
async def get_profile(
    profile_id: UUID, service: ProfileAdminService = Depends(get_profile_admin_service)
):
    return await service.get_profile(profile_id)


@router.patch("/{profile_id}", response_model=ProfileDetail, summary='Alterar perfil', description='Altera apenas os campos enviados (ao menos um).', responses=admin_responses(ProfileNotFoundError, ProfileNameAlreadyExistsError))
async def update_profile(
    profile_id: UUID,
    body: ProfileUpdate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: ProfileAdminService = Depends(get_profile_admin_service),
):
    return await service.update_profile(profile_id, body, actor)


@router.delete("/{profile_id}", status_code=204, summary='Excluir perfil', description='Exclui o perfil e seus vínculos com usuários e analyses.', responses=admin_responses(ProfileNotFoundError))
async def delete_profile(
    profile_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: ProfileAdminService = Depends(get_profile_admin_service),
):
    await service.delete_profile(profile_id, actor)
    return Response(status_code=204)


@router.put("/{profile_id}/analyses", response_model=ProfileDetail, summary='Definir analyses do perfil', description='Substitui o conjunto de analyses liberadas ao perfil (lista vazia remove todas).', responses=admin_responses(ProfileNotFoundError, InvalidReferenceError))
async def set_profile_analyses(
    profile_id: UUID,
    body: AnalysisIdsBody,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: ProfileAdminService = Depends(get_profile_admin_service),
):
    return await service.set_analyses(profile_id, body.analysis_ids, actor)


@router.put("/{profile_id}/users", response_model=ProfileDetail, summary='Definir usuários do perfil', description='Substitui o conjunto de usuários do perfil (lista vazia remove todos).', responses=admin_responses(ProfileNotFoundError, InvalidReferenceError))
async def set_profile_users(
    profile_id: UUID,
    body: UserIdsBody,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: ProfileAdminService = Depends(get_profile_admin_service),
):
    return await service.set_users(profile_id, body.user_ids, actor)
