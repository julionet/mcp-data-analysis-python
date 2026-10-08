"""Modelos e exceções da API administrativa — F23_API_ADMIN_USUARIOS_PERFIS.md §4.4/§4.5.

Respostas tipam e-mail como `str` (não `EmailStr`): o login `admin` do seed não é um
e-mail válido. Nenhum modelo de resposta tem `password_hash` nem `token_hash`.
Toda exceção de domínio herda de `AdminError` e carrega o status HTTP e o slug do
formato de erro `{"error", "message"}` (ADR-008); `routes/admin_route.py` a traduz.
"""

from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator

T = TypeVar("T")


# ---- exceções ----


class AdminError(Exception):
    status_code = 400
    error = "bad_request"

    def __init__(self, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.headers = headers


class UnauthorizedError(AdminError):
    status_code = 401
    error = "unauthorized"


class ForbiddenError(AdminError):
    status_code = 403
    error = "forbidden"


class UserNotFoundError(AdminError):
    status_code = 404
    error = "user_not_found"

    def __init__(self) -> None:
        super().__init__("Usuário não encontrado.")


class ProfileNotFoundError(AdminError):
    status_code = 404
    error = "profile_not_found"

    def __init__(self) -> None:
        super().__init__("Perfil não encontrado.")


class AdminTokenNotFoundError(AdminError):
    status_code = 404
    error = "token_not_found"

    def __init__(self) -> None:
        super().__init__("Token não encontrado.")


class EmailAlreadyExistsError(AdminError):
    status_code = 409
    error = "email_already_exists"

    def __init__(self) -> None:
        super().__init__("Já existe um usuário com este e-mail.")


class ProfileNameAlreadyExistsError(AdminError):
    status_code = 409
    error = "profile_name_already_exists"

    def __init__(self) -> None:
        super().__init__("Já existe um perfil com este nome.")


class UserHasHistoryError(AdminError):
    status_code = 409
    error = "user_has_history"

    def __init__(self) -> None:
        super().__init__(
            "O usuário tem histórico de execuções e não pode ser excluído; bloqueie-o."
        )


class SelfProtectedError(AdminError):
    status_code = 409
    error = "self_protected"

    def __init__(self) -> None:
        super().__init__(
            "O administrador não pode bloquear, excluir nem remover o próprio papel de administrador."
        )


class LastAdminProtectedError(AdminError):
    status_code = 409
    error = "last_admin_protected"

    def __init__(self) -> None:
        super().__init__("A operação deixaria o sistema sem administrador ativo.")


class InvalidPasswordError(AdminError):
    status_code = 400
    error = "invalid_password"


class InvalidCurrentPasswordError(AdminError):
    status_code = 400
    error = "invalid_current_password"

    def __init__(self) -> None:
        super().__init__("Senha atual incorreta.")


class InvalidReferenceError(AdminError):
    status_code = 422
    error = "invalid_reference"

    def __init__(self, kind: str, missing: list[UUID]) -> None:
        super().__init__(f"{kind} inexistentes: {', '.join(str(i) for i in missing)}.")
        self.missing = missing


# ---- requests ----


class _AtLeastOneField(BaseModel):
    @model_validator(mode="after")
    def _not_empty(self):
        if not self.model_fields_set:
            raise ValueError("Informe ao menos um campo para alterar.")
        return self


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr = Field(max_length=255)
    password: str = Field(max_length=256)  # a política (72 bytes etc.) é validada no serviço
    is_admin: bool = False
    profile_ids: list[UUID] = []


class UserUpdate(_AtLeastOneField):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)
    is_admin: bool | None = None


class PasswordBody(BaseModel):
    password: str = Field(max_length=256)


class ProfileIdsBody(BaseModel):
    profile_ids: list[UUID]


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    is_active: bool = True


class ProfileUpdate(_AtLeastOneField):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_active: bool | None = None


class AnalysisIdsBody(BaseModel):
    analysis_ids: list[UUID]


class UserIdsBody(BaseModel):
    user_ids: list[UUID]


class ChangePasswordBody(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


# ---- responses ----


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ProfileRef(BaseModel):
    id: UUID
    name: str
    is_active: bool


class UserSummary(BaseModel):
    id: UUID
    name: str
    email: str | None
    is_blocked: bool
    is_admin: bool
    created_at: datetime | None
    updated_at: datetime | None


class UserDetail(UserSummary):
    created_by: str | None
    profiles: list[ProfileRef]
    active_tokens: int


class TokenInfo(BaseModel):
    id: UUID
    label: str | None
    created_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None


class RevokedCount(BaseModel):
    revoked: int


class Me(BaseModel):
    id: UUID
    name: str
    email: str | None
    is_admin: bool
    profiles: list[ProfileRef]


class ProfileSummary(BaseModel):
    id: UUID
    name: str
    description: str | None
    is_active: bool
    users_count: int
    analyses_count: int
    created_at: datetime | None
    updated_at: datetime | None


class ProfileUserRef(BaseModel):
    id: UUID
    name: str
    email: str | None
    is_blocked: bool


class ProfileAnalysisRef(BaseModel):
    id: UUID
    name: str
    is_active: bool


class ProfileDetail(ProfileSummary):
    users: list[ProfileUserRef]
    analyses: list[ProfileAnalysisRef]
