"""list_tools() / call_tool() — F5_MCP_TOOLS_INTEGRATION.md §4.2/§4.4.

Agnóstico de qual análise está sendo processada (§8.3 da spec): nenhuma
lógica específica de uma análise pode viver aqui. Toda análise ativa e com
nome válido em `analyses` vira uma Tool MCP `execute_<nome>`; call_tool()
resolve qual análise executar a partir do nome recebido do protocolo.
"""

import logging
import re

from mcp.types import Tool

from config import settings
from database.connection import config_db_adapter
from repositories.analysis_repo import Analysis, AnalysisRepository
from repositories.data_source_repo import DataSourceRepository
from schemas.analysis_parameters import to_json_schema
from services.analysis_service import AnalysisService
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
analysis_service = AnalysisService(analysis_repo, _data_source_repo, _volume_guard)


def _build_tool(analysis: Analysis) -> Tool:
    input_schema = to_json_schema(analysis.parameters)
    input_schema["properties"]["confirmar_volume_alto"] = _CONFIRMAR_VOLUME_ALTO_PROPERTY
    return Tool(
        name=f"execute_{analysis.name}",
        description=analysis.description or "",
        inputSchema=input_schema,
    )


async def list_tools() -> list[Tool]:
    """Gera dinamicamente uma Tool MCP por análise ativa e com nome válido.
    Análises com nome fora do padrão de identificador MCP são ignoradas
    (logadas como warning), nunca viram uma tool inválida."""
    tools: list[Tool] = []
    for analysis in await analysis_service.get_all_analyses():
        if not _NAME_PATTERN.match(analysis.name):
            logger.warning(
                "Análise '%s' ignorada em list_tools(): nome fora do padrão %s",
                analysis.name,
                _NAME_PATTERN.pattern,
            )
            continue
        tools.append(_build_tool(analysis))
    return tools


async def call_tool(name: str, arguments: dict) -> dict:
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

    confirmar_volume_alto = arguments.pop("confirmar_volume_alto", False)
    return await analysis_service.execute(analysis.id, arguments, confirmar_volume_alto)
