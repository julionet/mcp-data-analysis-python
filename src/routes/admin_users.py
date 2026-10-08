"""/admin/users — F23 §4.4.2. Todas as rotas exigem administrador (`require_admin`)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from routes.admin_route import AdminRoute
from routes.dependencies import get_user_admin_service
from schemas.admin import (
    Page,
    PasswordBody,
    ProfileIdsBody,
    RevokedCount,
    TokenInfo,
    UserCreate,
    UserDetail,
    UserSummary,
    UserUpdate,
)
from schemas.auth import AuthenticatedUser
from security.admin_auth import get_current_user, require_admin
from services.user_admin_service import UserAdminService

router = APIRouter(
    prefix="/admin/users",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
    route_class=AdminRoute,
)


@router.get("", response_model=Page[UserSummary])
async def list_users(
    q: str | None = None,
    is_blocked: bool | None = None,
    profile_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return await service.list_users(q, is_blocked, profile_id, limit, offset)


@router.post("", status_code=201, response_model=UserDetail)
async def create_user(
    body: UserCreate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return await service.create_user(body, actor)


@router.get("/{user_id}", response_model=UserDetail)
async def get_user(user_id: UUID, service: UserAdminService = Depends(get_user_admin_service)):
    return await service.get_user(user_id)


@router.patch("/{user_id}", response_model=UserDetail)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return await service.update_user(user_id, body, actor)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    await service.delete_user(user_id, actor)
    return Response(status_code=204)


@router.put("/{user_id}/password", status_code=204)
async def reset_password(
    user_id: UUID,
    body: PasswordBody,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    await service.reset_password(user_id, body.password, actor)
    return Response(status_code=204)


@router.post("/{user_id}/block", response_model=UserDetail)
async def block_user(
    user_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return await service.set_blocked(user_id, True, actor)


@router.post("/{user_id}/unblock", response_model=UserDetail)
async def unblock_user(
    user_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return await service.set_blocked(user_id, False, actor)


@router.put("/{user_id}/profiles", response_model=UserDetail)
async def set_user_profiles(
    user_id: UUID,
    body: ProfileIdsBody,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return await service.set_profiles(user_id, body.profile_ids, actor)


@router.get("/{user_id}/tokens", response_model=list[TokenInfo])
async def list_tokens(user_id: UUID, service: UserAdminService = Depends(get_user_admin_service)):
    return await service.list_tokens(user_id)


@router.delete("/{user_id}/tokens/{token_id}", status_code=204)
async def revoke_token(
    user_id: UUID,
    token_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    await service.revoke_token(user_id, token_id, actor)
    return Response(status_code=204)


@router.delete("/{user_id}/tokens", response_model=RevokedCount)
async def revoke_all_tokens(
    user_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return RevokedCount(revoked=await service.revoke_all_tokens(user_id, actor))
