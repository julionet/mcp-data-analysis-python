"""/admin/users — F23 §4.4.2. Todas as rotas exigem administrador (`require_admin`)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from routes.admin_route import AdminRoute
from routes.openapi_docs import TAG_USERS, admin_responses
from routes.dependencies import get_user_admin_service
from schemas.admin import (
    AdminTokenNotFoundError,
    EmailAlreadyExistsError,
    InvalidPasswordError,
    InvalidReferenceError,
    LastAdminProtectedError,
    Page,
    PasswordBody,
    ProfileIdsBody,
    RevokedCount,
    SelfProtectedError,
    TokenInfo,
    UserCreate,
    UserDetail,
    UserHasHistoryError,
    UserNotFoundError,
    UserSummary,
    UserUpdate,
)
from schemas.auth import AuthenticatedUser
from security.admin_auth import get_current_user, require_admin
from services.user_admin_service import UserAdminService

router = APIRouter(
    prefix="/admin/users",
    tags=[TAG_USERS],
    dependencies=[Depends(require_admin)],
    route_class=AdminRoute,
)


@router.get("", response_model=Page[UserSummary], summary='Listar usuários', description='Lista paginada, com busca textual (`q`, nome ou e-mail) e filtros por bloqueio e perfil.', responses=admin_responses())
async def list_users(
    q: str | None = None,
    is_blocked: bool | None = None,
    profile_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return await service.list_users(q, is_blocked, profile_id, limit, offset)


@router.post("", status_code=201, response_model=UserDetail, summary='Criar usuário', description='Cria o usuário com senha inicial (política: mínimo 6 caracteres, maiúscula, minúscula, número e símbolo) e vincula os perfis informados, numa transação.', responses=admin_responses(InvalidPasswordError, EmailAlreadyExistsError, InvalidReferenceError))
async def create_user(
    body: UserCreate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return await service.create_user(body, actor)


@router.get("/{user_id}", response_model=UserDetail, summary='Detalhar usuário', description='Devolve o usuário com perfis e quantidade de tokens ativos. Nunca devolve hash de senha.', responses=admin_responses(UserNotFoundError))
async def get_user(user_id: UUID, service: UserAdminService = Depends(get_user_admin_service)):
    return await service.get_user(user_id)


@router.patch("/{user_id}", response_model=UserDetail, summary='Alterar usuário', description='Altera apenas os campos enviados (ao menos um). O administrador não pode remover o próprio papel, e o último administrador ativo não pode deixar de sê-lo.', responses=admin_responses(UserNotFoundError, EmailAlreadyExistsError, SelfProtectedError, LastAdminProtectedError))
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return await service.update_user(user_id, body, actor)


@router.delete("/{user_id}", status_code=204, summary='Excluir usuário', description='Exclusão física, só para usuário sem histórico de execuções; com histórico responde 409 e o caminho é bloquear (`POST /admin/users/{user_id}/block`). Não é possível excluir a si mesmo nem o último administrador ativo.', responses=admin_responses(UserNotFoundError, SelfProtectedError, LastAdminProtectedError, UserHasHistoryError))
async def delete_user(
    user_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    await service.delete_user(user_id, actor)
    return Response(status_code=204)


@router.put("/{user_id}/password", status_code=204, summary='Redefinir senha', description='Define uma nova senha para o usuário (política da criação). Revoga os tokens ativos dele.', responses=admin_responses(UserNotFoundError, InvalidPasswordError))
async def reset_password(
    user_id: UUID,
    body: PasswordBody,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    await service.reset_password(user_id, body.password, actor)
    return Response(status_code=204)


@router.post("/{user_id}/block", response_model=UserDetail, summary='Bloquear usuário', description='Bloqueia o usuário: ele perde o acesso na chamada seguinte. Não é possível bloquear a si mesmo nem o último administrador ativo.', responses=admin_responses(UserNotFoundError, SelfProtectedError, LastAdminProtectedError))
async def block_user(
    user_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return await service.set_blocked(user_id, True, actor)


@router.post("/{user_id}/unblock", response_model=UserDetail, summary='Desbloquear usuário', description='Remove o bloqueio do usuário.', responses=admin_responses(UserNotFoundError))
async def unblock_user(
    user_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return await service.set_blocked(user_id, False, actor)


@router.put("/{user_id}/profiles", response_model=UserDetail, summary='Definir perfis do usuário', description='Substitui o conjunto de perfis do usuário (lista vazia remove todos).', responses=admin_responses(UserNotFoundError, InvalidReferenceError))
async def set_user_profiles(
    user_id: UUID,
    body: ProfileIdsBody,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return await service.set_profiles(user_id, body.profile_ids, actor)


@router.get("/{user_id}/tokens", response_model=list[TokenInfo], summary='Listar tokens do usuário', description='Lista os tokens do usuário (id, rótulo, datas). O valor do token nunca é devolvido.', responses=admin_responses(UserNotFoundError))
async def list_tokens(user_id: UUID, service: UserAdminService = Depends(get_user_admin_service)):
    return await service.list_tokens(user_id)


@router.delete("/{user_id}/tokens/{token_id}", status_code=204, summary='Revogar um token', description='Revoga um token específico do usuário.', responses=admin_responses(UserNotFoundError, AdminTokenNotFoundError))
async def revoke_token(
    user_id: UUID,
    token_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    await service.revoke_token(user_id, token_id, actor)
    return Response(status_code=204)


@router.delete("/{user_id}/tokens", response_model=RevokedCount, summary='Revogar todos os tokens', description='Revoga todos os tokens ativos do usuário e devolve quantos foram revogados.', responses=admin_responses(UserNotFoundError))
async def revoke_all_tokens(
    user_id: UUID,
    actor: AuthenticatedUser = Depends(get_current_user),
    service: UserAdminService = Depends(get_user_admin_service),
):
    return RevokedCount(revoked=await service.revoke_all_tokens(user_id, actor))
