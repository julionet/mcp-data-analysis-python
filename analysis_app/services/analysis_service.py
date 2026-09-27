"""Analysis Execution Engine — núcleo do fluxo "pedir análise → receber dado
real". Ver F4_EXECUTION_ENGINE.md §4.2 para o fluxo completo.

F5 (ajuste retroativo, F5_MCP_TOOLS_INTEGRATION.md §4.2 Fluxo B / §4.4):
execute() deixou de propagar exceção — todo caminho de saída é um dict
estruturado ("success" / "volume_exceeded" / "error"), pois é chamado
diretamente por mcp_transport/tools.py::call_tool(), que nunca pode deixar
uma exceção vazar para o transporte MCP.

F4 (ajuste retroativo, 2026-09-26): o adapter de cada data_source deixou de
ser criado/conectado/desconectado a cada execute() — um pool inteiro
(asyncpg.create_pool, default 10 conexões) era aberto e fechado por query,
o que não escalava sob chamadas concorrentes (RNF4). Agora o adapter é
cacheado por data_source_id em self._adapters e reutilizado entre chamadas;
só é fechado no shutdown, via aclose() (ver main.py).

F7: execute() passa a resolver o cache antes de tocar o BD — ver
F7_CACHE_SERVICE.md §4.2. A query em si (data_source → adapter → steps →
Volume Guard → query) virou _run_query(), usada como "executor" passado a
CacheService.get_or_execute(). Todo retorno de execute() ganha o campo
"cached" (tabela de contrato em F7_CACHE_SERVICE.md §4.4).
"""

import asyncio
import logging
import re
from uuid import UUID

from pydantic import ValidationError

from adapters.base import DatabaseAdapter
from adapters.factory import AdapterFactory
from repositories.analysis_repo import Analysis, AnalysisRepository
from repositories.data_source_repo import DataSource, DataSourceRepository
from schemas.analysis_parameters import to_pydantic_model, validate_schema
from schemas.exceptions import (
    AnalysisNotFoundError,
    DataSourceConnectionError,
    InvalidAnalysisSchemaError,
    InvalidCacheFrequencyError,
    InvalidParametersError,
    VolumeExceededError,
)
from security.crypto import decrypt_password
from services.cache_service import CacheService
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
        cache_service: CacheService,
    ) -> None:
        self.analysis_repo = analysis_repo
        self.data_source_repo = data_source_repo
        self.volume_guard = volume_guard
        self.cache_service = cache_service
        self._adapters: dict[UUID, DatabaseAdapter] = {}
        self._adapters_lock = asyncio.Lock()

    async def execute(
        self,
        analysis_id: UUID,
        params: dict,
        confirmar_volume_alto: bool = False,
    ) -> dict:
        """Executa uma análise e SEMPRE retorna um dict estruturado — nunca
        propaga exceção (F5, ajuste retroativo). Formatos possíveis:
          {"status": "success", "data": [...], "cached": bool}
          {"status": "success", "data": [...], "aviso": "...", "cached": bool}
          {"status": "volume_exceeded", "estimativa": {...}, "limite": {...}, "mensagem": "...", "cached": false}
          {"status": "error", "mensagem": "...", "cached": false}
        """
        try:
            return await self._execute(analysis_id, params, confirmar_volume_alto)
        except (
            AnalysisNotFoundError,
            InvalidAnalysisSchemaError,
            InvalidParametersError,
            DataSourceConnectionError,
            InvalidCacheFrequencyError,
        ) as exc:
            return {"status": "error", "mensagem": str(exc), "cached": False}
        except Exception:
            logger.exception("Erro inesperado ao executar a análise '%s'", analysis_id)
            return {
                "status": "error",
                "mensagem": "Erro interno ao executar a análise.",
                "cached": False,
            }

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

        ttl_seconds = CacheService.resolve_ttl(analysis.cache_frequency)

        async def executor() -> dict:
            return await self._run_query(analysis, validated_params, confirmar_volume_alto)

        if ttl_seconds is None:  # cache_frequency == "none" — pula o cache (F7_CACHE_SERVICE.md §4.2)
            logger.info("Cache BYPASS (cache_frequency='none') para a análise '%s'", analysis.name)
            result = await executor()
            return {**result, "cached": False}

        key = self.cache_service.build_key(
            analysis.id, analysis.updated_at, validated_params.model_dump()
        )
        return await self.cache_service.get_or_execute(
            key, ttl_seconds, confirmar_volume_alto, executor
        )

    async def _run_query(
        self,
        analysis: Analysis,
        validated_params,
        confirmar_volume_alto: bool,
    ) -> dict:
        """Data source → adapter → steps → Volume Guard → query — o "executor"
        passado a CacheService.get_or_execute() em um miss. Nunca é chamado em
        um cache hit (F7_CACHE_SERVICE.md §4.2)."""
        data_source = await self.data_source_repo.get_by_id(analysis.data_source_id)
        if data_source is None or not data_source.is_active:
            raise DataSourceConnectionError(
                f"Data source da análise '{analysis.name}' não encontrado ou inativo"
            )

        try:
            adapter = await self._get_adapter(data_source)
        except Exception as exc:
            logger.exception(
                "Falha ao conectar ao data source '%s'", data_source.name
            )
            raise DataSourceConnectionError(
                f"Não foi possível conectar ao data source '{data_source.name}'"
            ) from exc

        steps = await self.analysis_repo.get_steps(analysis.id)
        step = steps[0]  # step_order=1, type='query' — único tipo em uso em V1.0
        param_names = step.definition["params"]
        translated_sql = _translate_named_params(step.definition["sql"], param_names)
        count_sql = f"SELECT COUNT(*) FROM ({translated_sql}) AS sub"

        values = validated_params.model_dump()
        ordered_values = {name: values[name] for name in param_names}

        try:
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

    async def _get_adapter(self, data_source: DataSource) -> DatabaseAdapter:
        """Reutiliza um adapter (e seu pool) por data_source_id entre
        execuções, em vez de abrir/fechar um pool inteiro a cada chamada
        (ajuste retroativo — ver nota de módulo). Só entra no cache depois
        de connect() ter sucesso, para não reter um adapter quebrado."""
        adapter = self._adapters.get(data_source.id)
        if adapter is not None:
            return adapter

        async with self._adapters_lock:
            adapter = self._adapters.get(data_source.id)
            if adapter is not None:
                return adapter

            adapter_config = {
                **data_source.connection_config,
                "password": decrypt_password(data_source.connection_config["password"]),
            }
            adapter = AdapterFactory.create_adapter(data_source.type, adapter_config)
            await adapter.connect()
            self._adapters[data_source.id] = adapter
            return adapter

    async def aclose(self) -> None:
        """Fecha todos os pools de adapter cacheados. Chamado no shutdown do
        FastAPI (main.py), nunca durante execute()."""
        for adapter in self._adapters.values():
            await adapter.disconnect()
        self._adapters.clear()
