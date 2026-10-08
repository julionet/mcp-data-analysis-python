"""GET /me e PUT /me/password — F23 §4.4.4. Qualquer usuário autenticado (não exige is_admin)."""

from fastapi import APIRouter, Depends, Response

from routes.admin_route import AdminRoute
from routes.dependencies import get_user_admin_service
from schemas.admin import ChangePasswordBody, Me
from schemas.auth import AuthenticatedUser
from security.admin_auth import get_current_user
from services.user_admin_service import UserAdminService

router = APIRouter(prefix="/me", tags=["me"], route_class=AdminRoute)


@router.get("", response_model=Me)
async def get_me(
    user: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return await service.get_me(user)


@router.put("/password", status_code=204)
async def change_password(
    body: ChangePasswordBody,
    user: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    await service.change_own_password(user, body.current_password, body.new_password)
    return Response(status_code=204)
