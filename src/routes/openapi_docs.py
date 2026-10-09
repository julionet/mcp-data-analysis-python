"""Metadados OpenAPI compartilhados pelas rotas — F16_API_DOCUMENTATION.md §4.4/§4.5.

Só descreve o contrato no Swagger; não altera o comportamento das rotas. Os slugs e os
códigos HTTP das respostas de erro vêm das próprias classes `AdminError` (`schemas/admin.py`):
uma classe nova sem entrada em algum `responses=` é pega por `tests/test_openapi_docs.py`.
"""

from typing import Any

from schemas.admin import (
    AdminError,
    ErrorResponse,
    ForbiddenError,
    UnauthorizedError,
    ValidationErrorBody,
)

TAG_AUTH = "auth"
TAG_ME = "me"
TAG_HEALTH = "health"
TAG_USERS = "admin-users"
TAG_PROFILES = "admin-profiles"
TAG_DATA_SOURCES = "admin-data-sources"
TAG_ANALYSES = "admin-analyses"
TAG_EXECUTIONS = "admin-executions"

OPENAPI_TAGS = [
    {"name": TAG_AUTH, "description": "Emissão e revogação de tokens de acesso (e-mail + senha). Não exigem `Authorization`."},
    {"name": TAG_ME, "description": "Dados e senha do próprio usuário autenticado (qualquer usuário, não só administradores)."},
    {"name": TAG_USERS, "description": "Administração de usuários, perfis do usuário e tokens. Exige administrador."},
    {"name": TAG_PROFILES, "description": "Administração de perfis e do que cada perfil libera. Exige administrador."},
    {"name": TAG_DATA_SOURCES, "description": "Cadastro de fontes de dados e teste de conexão. Exige administrador."},
    {"name": TAG_ANALYSES, "description": "Cadastro de analyses (definição, query, perfis, cache). Exige administrador."},
    {"name": TAG_EXECUTIONS, "description": "Histórico de execuções e estatísticas, somente leitura. Exige administrador."},
    {"name": TAG_HEALTH, "description": "Verificação de saúde do servidor e do Config DB."},
]

_STATUS_TITLES = {
    400: "Requisição inválida",
    401: "Não autenticado",
    403: "Sem permissão",
    404: "Não encontrado",
    409: "Conflito",
    422: "Entidade não processável",
}

_VALIDATION_NOTE = (
    "Também pode vir no formato padrão do FastAPI (`{\"detail\": [...]}`) quando o corpo ou os "
    "parâmetros não passam na validação."
)


def slug_response(
    status_code: int, slugs: list[str], description: str | None = None, validation: bool = False
) -> dict[str, Any]:
    """Uma entrada de `responses=` para um status de erro, com os slugs possíveis na descrição."""
    text = description or _STATUS_TITLES.get(status_code, "Erro")
    text = f"{text}. Slugs: " + ", ".join(f"`{slug}`" for slug in slugs) + "."
    model: Any = ErrorResponse
    if validation:
        text += " " + _VALIDATION_NOTE
        model = ErrorResponse | ValidationErrorBody
    return {"model": model, "description": text}


def _build(errors: tuple[type[AdminError], ...]) -> dict[int | str, dict[str, Any]]:
    by_status: dict[int, list[str]] = {}
    for cls in errors:
        slugs = by_status.setdefault(cls.status_code, [])
        if cls.error not in slugs:
            slugs.append(cls.error)
    return {
        status: slug_response(status, slugs, validation=(status == 422))
        for status, slugs in sorted(by_status.items())
    }


def me_responses(*errors: type[AdminError]) -> dict[int | str, dict[str, Any]]:
    """Rotas de qualquer usuário autenticado: 401 + erros de domínio informados."""
    return _build((UnauthorizedError, *errors))


def admin_responses(*errors: type[AdminError]) -> dict[int | str, dict[str, Any]]:
    """Rotas de administrador: 401 + 403 + erros de domínio informados."""
    return _build((UnauthorizedError, ForbiddenError, *errors))
