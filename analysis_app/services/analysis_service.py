"""Analysis Execution Engine — núcleo do fluxo "pedir análise → receber dado
real". Ver F4_EXECUTION_ENGINE.md §4.2 para o fluxo completo.

F5 (ajuste retroativo, F5_MCP_TOOLS_INTEGRATION.md §4.2 Fluxo B / §4.4):
execute() deixou de propagar exceção — todo caminho de saída é um dict
estruturado ("success" / "volume_exceeded" / "error"), pois é chamado
diretamente por mcp_transport/tools.py::call_tool(), que nunca pode deixar
uma exceção vazar para o transporte MCP.
"""

import logging
import re
from uuid import UUID

from pydantic import ValidationError

from adapters.factory import AdapterFactory
from repositories.analysis_repo import Analysis, AnalysisRepository
from repositories.data_source_repo import DataSourceRepository
from schemas.analysis_parameters import to_pydantic_model, validate_schema
from schemas.exceptions import (
    AnalysisNotFoundError,
    DataSourceConnectionError,
    InvalidAnalysisSchemaError,
    InvalidParametersError,
    VolumeExceededError,
)
from security.crypto import decrypt_password
from services.volume_guard_service import VolumeGuardService

logger = logging.getLogger(__name__)


def _translate_named_params(sql: str, param_names: list[str]) -> str:
    """Traduz placeholders nomeados (":nome") para posicionais ($1, $2, ...)
    do asyncpg, na ordem de definition["params"] — decisão registrada em
    F4_EXECUTION_ENGINE.md §4.2."""
    translated = sql
    for index, name in enumerate(param_names, start=1):
        translated = re.sub(rf":{re.escape(name)}\b", f"${index}", translated)
    return translated


def _format_validation_error(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()]
    return "Parâmetros inválidos — " + "; ".join(parts)


class AnalysisService:
    def __init__(
        self,
        analysis_repo: AnalysisRepository,
        data_source_repo: DataSourceRepository,
        volume_guard: VolumeGuardService,
    ) -> None:
        self.analysis_repo = analysis_repo
        self.data_source_repo = data_source_repo
        self.volume_guard = volume_guard

    async def execute(
        self,
        analysis_id: UUID,
        params: dict,
        confirmar_volume_alto: bool = False,
    ) -> dict:
        """Executa uma análise e SEMPRE retorna um dict estruturado — nunca
        propaga exceção (F5, ajuste retroativo). Formatos possíveis:
          {"status": "success", "data": [...]}
          {"status": "success", "data": [...], "aviso": "..."}  (confirmar_volume_alto=true)
          {"status": "volume_exceeded", "estimativa": {...}, "limite": {...}, "mensagem": "..."}
          {"status": "error", "mensagem": "..."}
        """
        try:
            return await self._execute(analysis_id, params, confirmar_volume_alto)
        except (
            AnalysisNotFoundError,
            InvalidAnalysisSchemaError,
            InvalidParametersError,
            DataSourceConnectionError,
        ) as exc:
            return {"status": "error", "mensagem": str(exc)}
        except Exception:
            logger.exception("Erro inesperado ao executar a análise '%s'", analysis_id)
            return {"status": "error", "mensagem": "Erro interno ao executar a análise."}

    async def _execute(
        self,
        analysis_id: UUID,
        params: dict,
        confirmar_volume_alto: bool,
    ) -> dict:
        analysis = await self.analysis_repo.get_by_id(analysis_id)
        if analysis is None:
            raise AnalysisNotFoundError(analysis_id)

        validate_schema(analysis.parameters)

        params_model = to_pydantic_model(analysis.parameters)
        try:
            validated_params = params_model(**params)
        except ValidationError as exc:
            raise InvalidParametersError(_format_validation_error(exc)) from exc

        data_source = await self.data_source_repo.get_by_id(analysis.data_source_id)
        if data_source is None or not data_source.is_active:
            raise DataSourceConnectionError(
                f"Data source da análise '{analysis.name}' não encontrado ou inativo"
            )

        adapter_config = {
            **data_source.connection_config,
            "password": decrypt_password(data_source.connection_config["password"]),
        }
        adapter = AdapterFactory.create_adapter(data_source.type, adapter_config)

        steps = await self.analysis_repo.get_steps(analysis_id)
        step = steps[0]  # step_order=1, type='query' — único tipo em uso em V1.0
        param_names = step.definition["params"]
        translated_sql = _translate_named_params(step.definition["sql"], param_names)
        count_sql = f"SELECT COUNT(*) FROM ({translated_sql}) AS sub"

        values = validated_params.model_dump()
        ordered_values = {name: values[name] for name in param_names}

        try:
            await adapter.connect()
            if not confirmar_volume_alto:
                await self.volume_guard.check_row_count(adapter, count_sql, ordered_values)
            dataset = await adapter.execute_query(translated_sql, ordered_values)
        except VolumeExceededError as exc:
            return self.volume_guard.build_refinement_response(exc)
        except Exception as exc:
            logger.exception(
                "Falha ao executar a análise '%s' no data source '%s'",
                analysis.name,
                data_source.name,
            )
            raise DataSourceConnectionError(
                f"Não foi possível executar a análise no data source '{data_source.name}'"
            ) from exc
        finally:
            await adapter.disconnect()

        if not confirmar_volume_alto:
            try:
                self.volume_guard.check_serialized_size(dataset)
            except VolumeExceededError as exc:
                return self.volume_guard.build_refinement_response(exc)

        result = {"status": "success", "data": dataset}
        if confirmar_volume_alto:
            # bypass explícito — ARQUITETURA.md §3.4: "ignora o limite e devolve
            # o dataset completo, incluindo aviso"
            result["aviso"] = "resultado grande, enviado por confirmação explícita"
        return result

    async def get_all_analyses(self) -> list[Analysis]:
        """Lista análises ativas. Sem endpoint MCP nesta feature (isso é F5) —
        método já disponível no Service para o F5 consumir depois."""
        return await self.analysis_repo.get_all()
