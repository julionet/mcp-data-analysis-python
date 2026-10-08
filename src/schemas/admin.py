"""Modelos e exceções da API administrativa — F23_API_ADMIN_USUARIOS_PERFIS.md §4.4/§4.5.

Respostas tipam e-mail como `str` (não `EmailStr`): o login `admin` do seed não é um
e-mail válido. Nenhum modelo de resposta tem `password_hash` nem `token_hash`.
Toda exceção de domínio herda de `AdminError` e carrega o status HTTP e o slug do
formato de erro `{"error", "message"}` (ADR-008); `routes/admin_route.py` a traduz.
"""

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
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


class DataSourceNotFoundError(AdminError):
    status_code = 404
    error = "data_source_not_found"

    def __init__(self) -> None:
        super().__init__("Data source não encontrado.")


class AdminAnalysisNotFoundError(AdminError):
    status_code = 404
    error = "analysis_not_found"

    def __init__(self) -> None:
        super().__init__("Análise não encontrada.")


class DataSourceNameAlreadyExistsError(AdminError):
    status_code = 409
    error = "data_source_name_already_exists"

    def __init__(self) -> None:
        super().__init__("Já existe um data source com este nome.")


class AnalysisNameAlreadyExistsError(AdminError):
    status_code = 409
    error = "analysis_name_already_exists"

    def __init__(self) -> None:
        super().__init__("Já existe uma análise com este nome.")


class DataSourceHasAnalysesError(AdminError):
    status_code = 409
    error = "data_source_has_analyses"

    def __init__(self) -> None:
        super().__init__(
            "O data source tem análises vinculadas e não pode ser excluído; desative-o."
        )


class AnalysisHasHistoryError(AdminError):
    status_code = 409
    error = "analysis_has_history"

    def __init__(self) -> None:
        super().__init__(
            "A análise tem histórico de execuções e não pode ser excluída; desative-a."
        )


class InvalidConnectionConfigError(AdminError):
    status_code = 422
    error = "invalid_connection_config"


class UnsupportedDataSourceTypeError(AdminError):
    status_code = 422
    error = "unsupported_data_source_type"

    def __init__(self, type_: str, supported: list[str]) -> None:
        super().__init__(
            f"Tipo de data source '{type_}' não suportado. Tipos disponíveis: {', '.join(supported)}."
        )


class InvalidAnalysisDefinitionError(AdminError):
    status_code = 422
    error = "invalid_analysis_definition"

    def __init__(self, issues: list["Issue"]) -> None:
        super().__init__(
            "Definição da análise inválida: " + "; ".join(f"{i.field}: {i.message}" for i in issues)
        )
        self.issues = issues


class ExecutionNotFoundError(AdminError):
    status_code = 404
    error = "execution_not_found"

    def __init__(self) -> None:
        super().__init__("Execução não encontrada.")


class InvalidPeriodError(AdminError):
    status_code = 422
    error = "invalid_period"


class InvalidParametersFilterError(AdminError):
    status_code = 422
    error = "invalid_parameters_filter"


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


# ---- F24: data sources ----


class DataSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=50)
    connection_config: dict[str, Any]
    is_active: bool = True


class DataSourceUpdate(_AtLeastOneField):
    """`type` não é alterável (F24 decisão 9). `connection_config` é mesclado com o salvo."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    connection_config: dict[str, Any] | None = None


class ConnectionTestBody(BaseModel):
    type: str = Field(min_length=1, max_length=50)
    connection_config: dict[str, Any]


class DataSourceSummary(BaseModel):
    id: UUID
    name: str
    type: str
    is_active: bool
    analyses_count: int
    created_by: str | None
    created_at: datetime | None
    updated_at: datetime | None


class DataSourceAnalysisRef(BaseModel):
    id: UUID
    name: str
    is_active: bool


class DataSourceDetail(DataSourceSummary):
    connection_config: dict[str, Any]  # nunca contém `password`
    has_password: bool
    analyses: list[DataSourceAnalysisRef]


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    error_type: str | None = None
    elapsed_ms: int


class DataSourceTypeInfo(BaseModel):
    type: str
    required: list[str]
    optional: list[dict[str, Any]]
    one_of: list[list[str]]


# ---- F24: analyses ----


class Issue(BaseModel):
    code: str
    field: str
    message: str


class ValidationReport(BaseModel):
    valid: bool
    errors: list[Issue]
    warnings: list[Issue]


class StepInput(BaseModel):
    sql: str = Field(min_length=1)
    params: list[str] = []


class StepUpdate(_AtLeastOneField):
    sql: str | None = Field(default=None, min_length=1)
    params: list[str] | None = None


class AnalysisCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    data_source_id: UUID
    cache_frequency: str = "daily"
    parameters: dict[str, Any] = {}
    is_active: bool = True
    step: StepInput
    profile_ids: list[UUID] = []


class AnalysisUpdate(_AtLeastOneField):
    """`parameters` substitui o objeto inteiro; `step` mescla `sql`/`params` sobre o atual."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    data_source_id: UUID | None = None
    cache_frequency: str | None = None
    parameters: dict[str, Any] | None = None
    is_active: bool | None = None
    step: StepUpdate | None = None


class AnalysisSummary(BaseModel):
    id: UUID
    name: str
    description: str | None
    data_source_id: UUID | None
    data_source_name: str | None
    cache_frequency: str
    is_active: bool
    profiles_count: int
    created_by: str | None
    created_at: datetime | None
    updated_at: datetime | None


class StepOut(BaseModel):
    id: UUID
    step_order: int
    step_type: str
    sql: str | None
    params: list[str]


class AnalysisDetail(AnalysisSummary):
    parameters: dict[str, Any]
    step: StepOut | None
    profiles: list[ProfileRef]


class InvalidateResult(BaseModel):
    invalidated: bool
    updated_at: datetime


# ---- F25: histórico de execuções (somente leitura) ----

ExecutionStatus = Literal["success", "volume_exceeded", "error", "timeout"]
# Os 7 códigos do contrato da F14 (ARQUITETURA.md §3.4.1); um teste os compara com schemas/exceptions.py.
ExecutionErrorCode = Literal[
    "ANALYSIS_NOT_FOUND",
    "INVALID_PARAMETERS",
    "INVALID_ANALYSIS_CONFIG",
    "DATA_SOURCE_UNAVAILABLE",
    "QUERY_TIMEOUT",
    "QUERY_FAILED",
    "INTERNAL_ERROR",
]


class ExecutionAnalysisRef(BaseModel):
    id: UUID
    name: str


class ExecutionUserRef(BaseModel):
    id: UUID
    name: str
    email: str  # users.external_id (str: o login "admin" do seed não é e-mail)


class ExecutionSummary(BaseModel):
    id: UUID
    analysis: ExecutionAnalysisRef
    user: ExecutionUserRef | None  # None em execuções pré-F12
    status: str
    error_code: str | None
    cached: bool
    parameters: dict[str, Any]
    execution_time_ms: int | None
    rows_affected: int | None
    result_size_bytes: int | None
    executed_at: datetime


class ExecutionDetail(ExecutionSummary):
    error_message: str | None


class StatusCounts(BaseModel):
    success: int
    volume_exceeded: int
    error: int
    timeout: int


class TimeStats(BaseModel):
    count: int
    avg: float | None
    p95: float | None
    max: int | None


class CacheStats(BaseModel):
    hits: int
    success: int
    hit_rate: float | None


class ExecutionTopAnalysis(BaseModel):
    analysis_id: UUID
    name: str
    count: int


class ExecutionTopUser(BaseModel):
    user_id: UUID
    name: str
    email: str
    count: int


class ExecutionStats(BaseModel):
    period: dict[str, datetime]
    total: int
    by_status: StatusCounts
    by_error_code: dict[str, int]
    cache: CacheStats
    execution_time_ms: dict[str, TimeStats]  # {"cache_hit": ..., "cache_miss": ...}
    top_analyses: list[ExecutionTopAnalysis]
    top_users: list[ExecutionTopUser]
