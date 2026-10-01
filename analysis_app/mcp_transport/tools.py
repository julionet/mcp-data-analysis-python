"""list_tools() / call_tool() — F5_MCP_TOOLS_INTEGRATION.md §4.2/§4.4.

Agnóstico de qual análise está sendo processada (§8.3 da spec): nenhuma
lógica específica de uma análise pode viver aqui. Toda análise ativa e com
nome válido em `analyses` vira uma Tool MCP `execute_<nome>`; call_tool()
resolve qual análise executar a partir do nome recebido do protocolo.

F12: ambas exigem o `AuthenticatedUser` (já validado pelo middleware do /mcp).
list_tools() só devolve o que o usuário pode ver; call_tool() REVALIDA a
permissão a cada chamada — nunca confia no que list_tools() já mostrou.
"""

import logging
import re

from mcp.types import Tool

from config import settings
from database.connection import config_db_adapter
from repositories.analysis_repo import Analysis, AnalysisRepository
from repositories.access_token_repo import AccessTokenRepository
from repositories.data_source_repo import DataSourceRepository
from repositories.execution_repo import ExecutionRepository
from repositories.profile_repo import ProfileRepository
from repositories.user_repo import UserRepository
from schemas.analysis_parameters import to_json_schema
from schemas.auth import AuthenticatedUser
from services.analysis_service import AnalysisService
from services.audit_service import AuditService
from services.auth_service import AuthService
from services.cache_backend import CacheBackend, InMemoryBackend, NullBackend
from services.cache_service import CacheService
from services.volume_guard_service import VolumeGuardService

logger = logging.getLogger(__name__)

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

_CONFIRMAR_VOLUME_ALTO_PROPERTY = {
    "type": "boolean",
    "default": False,
    "description": (
        "Confirma execução mesmo que o resultado seja grande "
        "(maior consumo de tokens)"
    ),
}

analysis_repo = AnalysisRepository(config_db_adapter)
_data_source_repo = DataSourceRepository(config_db_adapter)
_volume_guard = VolumeGuardService(
    settings.default_max_result_rows, settings.default_max_result_size_kb
)
# CACHE_BACKEND só aceita "memory"/"none" em V1.0 — outro valor já falhou no
# startup em config.py (Settings.model_post_init). "none" é o kill-switch
# global de cache (NullBackend, ajuste retroativo 2026-09-27). Um novo backend
# (Redis, F7_CACHE_SERVICE.md §8.3) entraria aqui como mais um branch.
_cache_backend: CacheBackend
if settings.cache_backend == "none":
    _cache_backend = NullBackend()
    logger.warning("CACHE_BACKEND=none - cache desligado globalmente para todas as análises")
else:
    _cache_backend = InMemoryBackend(settings.cache_max_entries, settings.cache_max_size_mb)
    logger.info(
        "Cache em memória ativo (CACHE_MAX_ENTRIES=%d, CACHE_MAX_SIZE_MB=%d)",
        settings.cache_max_entries,
        settings.cache_max_size_mb,
    )
_cache_service = CacheService(
    _cache_backend, settings.default_max_result_rows, settings.default_max_result_size_kb
)
_execution_repo = ExecutionRepository(config_db_adapter)
_audit_service = AuditService(_execution_repo)
analysis_service = AnalysisService(
    analysis_repo, _data_source_repo, _volume_guard, _cache_service, _audit_service
)
# Instância única do AuthService: o middleware do /mcp, as rotas /auth/* e
# call_tool() usam esta mesma (F12 §4.1). É o ponto que os testes patcham.
auth_service = AuthService(
    AccessTokenRepository(config_db_adapter),
    UserRepository(config_db_adapter),
    ProfileRepository(config_db_adapter),
)


def _build_tool(analysis: Analysis) -> Tool:
    input_schema = to_json_schema(analysis.parameters)
    input_schema["properties"]["confirmar_volume_alto"] = _CONFIRMAR_VOLUME_ALTO_PROPERTY
    return Tool(
        name=f"execute_{analysis.name}",
        description=analysis.description or "",
        inputSchema=input_schema,
    )


async def list_tools(current_user: AuthenticatedUser) -> list[Tool]:
    """Gera dinamicamente uma Tool MCP por análise ativa, com nome válido e
    liberada ao usuário (perfil ativo → análise ativa — F12).
    Análises com nome fora do padrão de identificador MCP são ignoradas
    (logadas como warning), nunca viram uma tool inválida."""
    tools: list[Tool] = []
    for analysis in await analysis_service.get_allowed_analyses(current_user.id):
        if not _NAME_PATTERN.match(analysis.name):
            logger.warning(
                "Análise '%s' ignorada em list_tools(): nome fora do padrão %s",
                analysis.name,
                _NAME_PATTERN.pattern,
            )
            continue
        tools.append(_build_tool(analysis))
    return tools


async def call_tool(name: str, arguments: dict, current_user: AuthenticatedUser) -> dict:
    """Único ponto de entrada de execução de análises via MCP. Resolve a
    análise pelo nome recebido do protocolo e repassa o resultado (já
    estruturado por AnalysisService.execute()) ao cliente MCP. Nunca propaga
    exceção — analysis_service.execute() já garante essa contrato."""
    analysis_name = name.removeprefix("execute_")
    analysis = await analysis_repo.get_by_name(analysis_name)
    if analysis is None or not analysis.is_active:
        return {
            "status": "error",
            "mensagem": f"Análise '{analysis_name}' não encontrada ou inativa.",
        }

    # F12: revalida a permissão a cada chamada, ANTES de qualquer cache/execução —
    # a tool pode ter aparecido num list_tools() anterior e o perfil mudado desde então.
    if not await auth_service.is_analysis_allowed(current_user.id, analysis.id):
        logger.warning(
            "access_denied user_id=%s analysis_id=%s analysis_name=%s",
            current_user.id,
            analysis.id,
            analysis.name,
        )
        return {"status": "error", "mensagem": "Acesso não autorizado a esta análise."}

    confirmar_volume_alto = arguments.pop("confirmar_volume_alto", False)
    return await analysis_service.execute(
        analysis.id, arguments, confirmar_volume_alto, user_id=current_user.id
    )
