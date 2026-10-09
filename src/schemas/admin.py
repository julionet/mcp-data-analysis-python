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


# ---- F16: corpos de erro (só descrevem o OpenAPI; as rotas seguem devolvendo JSONResponse) ----


class ErrorResponse(BaseModel):
    """Erro de domínio das rotas `/auth`, `/me` e `/admin` (ADR-008)."""

    error: str = Field(description="Slug estável do erro, ex.: `user_not_found`.")
    message: str = Field(description="Mensagem legível, em português.")

    model_config = {
        "json_schema_extra": {
            "example": {"error": "user_not_found", "message": "Usuário não encontrado."}
        }
    }


class ValidationErrorItem(BaseModel):
    loc: list[str | int] = Field(description="Caminho do campo inválido, ex.: `[\"body\", \"email\"]`.")
    msg: str = Field(description="Descrição do problema.")
    type: str = Field(description="Tipo do erro de validação (pydantic).")


class ValidationErrorBody(BaseModel):
    """422 de validação de corpo/parâmetros no formato padrão do FastAPI (não é o slug `error`/`message`)."""

    detail: list[ValidationErrorItem]


# ---- requests ----


class _AtLeastOneField(BaseModel):
    @model_validator(mode="after")
    def _not_empty(self):
        if not self.model_fields_set:
            raise ValueError("Informe ao menos um campo para alterar.")
        return self


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Nome do usuário.")
    email: EmailStr = Field(max_length=255, description="E-mail de login (único; normalizado em minúsculas).")
    password: str = Field(
        max_length=256,
        description="Senha inicial. Política: mínimo 6 caracteres, com maiúscula, minúscula, número e símbolo.",
    )  # a política (72 bytes etc.) é validada no serviço
    is_admin: bool = Field(default=False, description="Concede acesso à API administrativa.")
    profile_ids: list[UUID] = Field(default=[], description="Perfis a vincular ao usuário.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Maria Souza",
                "email": "maria@exemplo.com",
                "password": "Exemplo@123",
                "is_admin": False,
                "profile_ids": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
            }
        }
    }


class UserUpdate(_AtLeastOneField):
    """Informe ao menos um campo; os omitidos não são alterados."""

    name: str | None = Field(default=None, min_length=1, max_length=255, description="Novo nome.")
    email: EmailStr | None = Field(default=None, max_length=255, description="Novo e-mail (único).")
    is_admin: bool | None = Field(default=None, description="Concede ou remove o papel de administrador.")

    model_config = {"json_schema_extra": {"example": {"name": "Maria Souza Lima"}}}


class PasswordBody(BaseModel):
    password: str = Field(max_length=256, description="Nova senha (mesma política da criação).")

    model_config = {"json_schema_extra": {"example": {"password": "NovaSenha@456"}}}


class ProfileIdsBody(BaseModel):
    profile_ids: list[UUID] = Field(description="Conjunto completo de perfis; substitui o atual (lista vazia remove todos).")

    model_config = {"json_schema_extra": {"example": {"profile_ids": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"]}}}


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Nome do perfil (único).")
    description: str | None = Field(default=None, description="Descrição livre.")
    is_active: bool = Field(default=True, description="Perfil inativo não libera nenhuma análise.")

    model_config = {
        "json_schema_extra": {"example": {"name": "vendas", "description": "Equipe comercial", "is_active": True}}
    }


class ProfileUpdate(_AtLeastOneField):
    """Informe ao menos um campo; os omitidos não são alterados."""

    name: str | None = Field(default=None, min_length=1, max_length=255, description="Novo nome (único).")
    description: str | None = Field(default=None, description="Nova descrição.")
    is_active: bool | None = Field(default=None, description="Ativa ou desativa o perfil.")

    model_config = {"json_schema_extra": {"example": {"is_active": False}}}


class AnalysisIdsBody(BaseModel):
    analysis_ids: list[UUID] = Field(description="Conjunto completo de analyses liberadas ao perfil; substitui o atual.")

    model_config = {"json_schema_extra": {"example": {"analysis_ids": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"]}}}


class UserIdsBody(BaseModel):
    user_ids: list[UUID] = Field(description="Conjunto completo de usuários do perfil; substitui o atual.")

    model_config = {"json_schema_extra": {"example": {"user_ids": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"]}}}


class ChangePasswordBody(BaseModel):
    current_password: str = Field(max_length=256, description="Senha atual.")
    new_password: str = Field(max_length=256, description="Nova senha (mesma política da criação).")

    model_config = {
        "json_schema_extra": {"example": {"current_password": "Exemplo@123", "new_password": "NovaSenha@456"}}
    }


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
    name: str = Field(min_length=1, max_length=255, description="Nome do data source (único).")
    type: str = Field(min_length=1, max_length=50, description="Tipo do banco; veja `GET /admin/data-sources/types`.")
    connection_config: dict[str, Any] = Field(
        description="Parâmetros de conexão do tipo escolhido. A `password` é cifrada (Fernet) e nunca é devolvida."
    )
    is_active: bool = Field(default=True, description="Data source inativo não executa analyses.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "vendas_pg",
                "type": "postgresql",
                "connection_config": {
                    "host": "db.exemplo.com",
                    "port": 5432,
                    "database": "vendas",
                    "user": "leitura",
                    "password": "segredo",
                },
                "is_active": True,
            }
        }
    }


class DataSourceUpdate(_AtLeastOneField):
    """`type` não é alterável (F24 decisão 9). `connection_config` é mesclado com o salvo."""

    name: str | None = Field(default=None, min_length=1, max_length=255, description="Novo nome (único).")
    is_active: bool | None = Field(default=None, description="Ativa ou desativa o data source.")
    connection_config: dict[str, Any] | None = Field(
        default=None,
        description="Mesclado com a configuração salva: envie só as chaves a alterar (a senha só muda se enviada).",
    )

    model_config = {"json_schema_extra": {"example": {"connection_config": {"host": "novo-host.exemplo.com"}}}}


class ConnectionTestBody(BaseModel):
    type: str = Field(min_length=1, max_length=50, description="Tipo do banco.")
    connection_config: dict[str, Any] = Field(description="Configuração a testar (não é salva).")

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "postgresql",
                "connection_config": {
                    "host": "db.exemplo.com",
                    "port": 5432,
                    "database": "vendas",
                    "user": "leitura",
                    "password": "segredo",
                },
            }
        }
    }


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
    sql: str = Field(min_length=1, description="SQL da análise, com placeholders `:param`. Somente SELECT.")
    params: list[str] = Field(default=[], description="Nomes dos parâmetros usados no SQL, na ordem de uso.")


class StepUpdate(_AtLeastOneField):
    sql: str | None = Field(default=None, min_length=1, description="Novo SQL (somente SELECT).")
    params: list[str] | None = Field(default=None, description="Nova lista de parâmetros.")


class AnalysisCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Nome da análise (único); vira a tool `execute_<name>` no MCP.")
    description: str | None = Field(default=None, description="Descrição mostrada ao LLM no cliente MCP.")
    data_source_id: UUID = Field(description="Data source onde o SQL é executado.")
    cache_frequency: str = Field(default="daily", description="Frequência de renovação do cache.")
    parameters: dict[str, Any] = Field(default={}, description="Definição dos parâmetros de entrada (vira o `inputSchema` da tool).")
    is_active: bool = Field(default=True, description="Análise inativa não aparece nem executa no MCP.")
    step: StepInput = Field(description="Query da análise.")
    profile_ids: list[UUID] = Field(default=[], description="Perfis que podem executar a análise.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "vendas_por_regiao",
                "description": "Total de vendas por região no período",
                "data_source_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "cache_frequency": "daily",
                "parameters": {},
                "is_active": True,
                "step": {"sql": "SELECT regiao, SUM(valor) AS total FROM vendas GROUP BY regiao", "params": []},
                "profile_ids": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
            }
        }
    }


class AnalysisUpdate(_AtLeastOneField):
    """`parameters` substitui o objeto inteiro; `step` mescla `sql`/`params` sobre o atual."""

    name: str | None = Field(default=None, min_length=1, max_length=255, description="Novo nome (único).")
    description: str | None = Field(default=None, description="Nova descrição.")
    data_source_id: UUID | None = Field(default=None, description="Novo data source.")
    cache_frequency: str | None = Field(default=None, description="Nova frequência de cache.")
    parameters: dict[str, Any] | None = Field(default=None, description="Substitui a definição de parâmetros inteira.")
    is_active: bool | None = Field(default=None, description="Ativa ou desativa a análise.")
    step: StepUpdate | None = Field(default=None, description="Mescla `sql`/`params` sobre a query atual.")

    model_config = {"json_schema_extra": {"example": {"is_active": False}}}


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
