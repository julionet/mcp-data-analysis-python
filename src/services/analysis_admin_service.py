"""Regras de administração de analyses (análise + step + perfis) — F24 §4.5.

Reaproveita as validações do engine (`validate_schema`, `validate_select_only`) como fonte
única: a API recusa o que o engine recusaria. `analyses.updated_at` entra na chave do cache
(F7), então TODA alteração de análise/step o atualiza (feito no repositório).
"""

from typing import Any
from uuid import UUID

import asyncpg

from repositories.analysis_repo import AnalysisRepository
from repositories.data_source_repo import DataSource, DataSourceRepository
from repositories.profile_repo import ProfileRepository
from repositories.user_repo import UserRepository
from schemas.admin import (
    AdminAnalysisNotFoundError,
    AnalysisCreate,
    AnalysisDetail,
    AnalysisHasHistoryError,
    AnalysisNameAlreadyExistsError,
    AnalysisSummary,
    AnalysisUpdate,
    InvalidAnalysisDefinitionError,
    InvalidateResult,
    InvalidReferenceError,
    Issue,
    Page,
    ProfileRef,
    StepOut,
    ValidationReport,
)
from schemas.analysis_parameters import validate_schema
from schemas.auth import AuthenticatedUser
from schemas.exceptions import InvalidAnalysisSchemaError
from schemas.sql_validation import extract_placeholders, validate_select_only
from services.cache_service import CACHE_FREQUENCIES
from services.user_admin_service import log_admin_action

_DEFINITION_FIELDS = ("parameters", "cache_frequency", "data_source_id")


def validate_analysis_definition(
    *,
    parameters: Any,
    cache_frequency: str,
    sql: str | None,
    step_params: list[str] | None,
    data_source: DataSource | None,
) -> tuple[list[Issue], list[Issue]]:
    """Verificações estáticas da §4.5.3 → (erros, avisos). `sql=None` = análise sem step."""
    errors: list[Issue] = []
    warnings: list[Issue] = []

    def error(code: str, field: str, message: str) -> None:
        errors.append(Issue(code=code, field=field, message=message))

    parameters_ok = isinstance(parameters, dict) and all(
        isinstance(v, dict) for v in parameters.values()
    )
    if not parameters_ok:
        error("invalid_parameters_schema", "parameters", "Cada parâmetro deve ser um objeto.")
    else:
        try:
            validate_schema(parameters)
        except InvalidAnalysisSchemaError as exc:
            error("invalid_parameters_schema", "parameters", str(exc))

    if cache_frequency not in CACHE_FREQUENCIES:
        error(
            "invalid_cache_frequency", "cache_frequency",
            f"Valor inválido '{cache_frequency}'; aceitos: {', '.join(CACHE_FREQUENCIES)}.",
        )

    if sql is None:
        error("missing_step", "step", "A análise não possui step cadastrado.")
    else:
        try:
            validate_select_only(sql)
        except InvalidAnalysisSchemaError as exc:
            error("sql_not_allowed", "step.sql", str(exc))

        names = step_params or []
        declared = set(parameters) if parameters_ok else set()
        placeholders = extract_placeholders(sql)
        for name in sorted({n for n in names if names.count(n) > 1}):
            error("duplicate_step_param", "step.params", f"Parâmetro '{name}' repetido em params.")
        for name in dict.fromkeys(names):
            if parameters_ok and name not in declared:
                error(
                    "unknown_step_param", "step.params",
                    f"'{name}' está em params mas não existe em parameters.",
                )
            if name not in placeholders:
                error("param_not_in_sql", "step.params", f"'{name}' está em params mas não aparece no SQL como :{name}.")
        for name in placeholders:
            if name not in names:
                error(
                    "placeholder_not_declared", "step.sql",
                    f"O SQL usa :{name}, que não está em params (não seria traduzido).",
                )
        for name in sorted(declared - set(names)):
            warnings.append(
                Issue(code="parameter_not_used", field="parameters",
                      message=f"O parâmetro '{name}' não é usado pelo step.")
            )

    if data_source is None:
        error("data_source_not_found", "data_source_id", "O data source não existe.")
    elif not data_source.is_active:
        warnings.append(
            Issue(code="data_source_inactive", field="data_source_id",
                  message="O data source está inativo: a execução falhará com DATA_SOURCE_UNAVAILABLE.")
        )
    return errors, warnings


class AnalysisAdminService:
    def __init__(
        self,
        db,
        analyses: AnalysisRepository,
        data_sources: DataSourceRepository,
        profiles: ProfileRepository,
        users: UserRepository,
    ) -> None:
        self._db = db
        self._analyses = analyses
        self._data_sources = data_sources
        self._profiles = profiles
        self._users = users

    # ---- leitura ----

    async def _detail(self, analysis_id: UUID, db=None) -> AnalysisDetail:
        row = await self._analyses.get_admin_row(analysis_id, db)
        if row is None:
            raise AdminAnalysisNotFoundError()
        steps = await self._analyses.get_steps(analysis_id, db)
        step = steps[0] if steps else None
        profiles = await self._analyses.get_profiles(analysis_id, db)
        return AnalysisDetail(
            **row,
            step=StepOut(
                id=step.id, step_order=step.step_order, step_type=step.step_type,
                sql=step.definition.get("sql"), params=list(step.definition.get("params") or []),
            ) if step else None,
            profiles=[ProfileRef(**p) for p in profiles],
        )

    async def list_analyses(
        self, q: str | None, data_source_id: UUID | None, is_active: bool | None,
        limit: int, offset: int,
    ) -> Page[AnalysisSummary]:
        rows, total = await self._analyses.admin_list(q, data_source_id, is_active, limit, offset)
        return Page[AnalysisSummary](
            items=[AnalysisSummary(**r) for r in rows], total=total, limit=limit, offset=offset
        )

    async def get_analysis(self, analysis_id: UUID) -> AnalysisDetail:
        return await self._detail(analysis_id)

    # ---- escrita ----

    async def _created_by(self, actor: AuthenticatedUser) -> str | None:
        row = await self._users.get_by_id(actor.id)
        return row.external_id if row else None

    async def _check_profiles_exist(self, profile_ids: list[UUID], tx) -> None:
        if profile_ids:
            existing = await self._profiles.existing_ids("profiles", profile_ids, tx)
            missing = [i for i in profile_ids if i not in existing]
            if missing:
                raise InvalidReferenceError("Perfis", missing)

    async def _require_data_source(self, data_source_id: UUID, tx) -> DataSource:
        data_source = await self._data_sources.get_by_id(data_source_id, tx)
        if data_source is None:
            raise InvalidReferenceError("Data sources", [data_source_id])
        return data_source

    async def create_analysis(self, data: AnalysisCreate, actor: AuthenticatedUser) -> AnalysisDetail:
        profile_ids = list(dict.fromkeys(data.profile_ids))
        created_by = await self._created_by(actor)
        try:
            async with self._db.transaction() as tx:
                data_source = await self._require_data_source(data.data_source_id, tx)
                await self._check_profiles_exist(profile_ids, tx)
                errors, _ = validate_analysis_definition(
                    parameters=data.parameters, cache_frequency=data.cache_frequency,
                    sql=data.step.sql, step_params=data.step.params, data_source=data_source,
                )
                if errors:
                    raise InvalidAnalysisDefinitionError(errors)
                analysis_id = await self._analyses.create(
                    {
                        "name": data.name, "description": data.description,
                        "data_source_id": data.data_source_id,
                        "cache_frequency": data.cache_frequency, "parameters": data.parameters,
                        "is_active": data.is_active, "created_by": created_by,
                    },
                    tx,
                )
                await self._analyses.create_step(
                    analysis_id, {"sql": data.step.sql, "params": data.step.params}, tx
                )
                await self._analyses.replace_profiles(analysis_id, profile_ids, tx)
        except asyncpg.UniqueViolationError as exc:
            raise AnalysisNameAlreadyExistsError() from exc
        log_admin_action(actor.id, "create_analysis", "analysis", analysis_id)
        return await self._detail(analysis_id)

    async def update_analysis(
        self, analysis_id: UUID, data: AnalysisUpdate, actor: AuthenticatedUser
    ) -> AnalysisDetail:
        sent = data.model_fields_set
        # colunas NOT NULL: enviar null equivale a não enviar; só `description` aceita null
        fields = {
            name: getattr(data, name)
            for name in ("name", "description", "data_source_id", "cache_frequency", "parameters", "is_active")
            if name in sent and (name == "description" or getattr(data, name) is not None)
        }
        step_patch = data.step if "step" in sent else None
        try:
            async with self._db.transaction() as tx:
                row = await self._analyses.get_admin_row(analysis_id, tx)
                if row is None:
                    raise AdminAnalysisNotFoundError()
                if "data_source_id" in fields:
                    await self._require_data_source(fields["data_source_id"], tx)
                steps = await self._analyses.get_steps(analysis_id, tx)
                current = steps[0] if steps else None
                sql = current.definition.get("sql") if current else None
                step_params = list(current.definition.get("params") or []) if current else []
                if step_patch is not None:
                    sql = step_patch.sql if step_patch.sql is not None else sql
                    step_params = step_patch.params if step_patch.params is not None else step_params

                # Só valida quando a alteração toca a definição: desativar/renomear uma análise
                # legada inconsistente continua possível (F24 §12).
                if step_patch is not None or any(f in fields for f in _DEFINITION_FIELDS):
                    data_source = await self._data_sources.get_by_id(
                        fields.get("data_source_id", row["data_source_id"]), tx
                    )
                    errors, _ = validate_analysis_definition(
                        parameters=fields.get("parameters", row["parameters"]),
                        cache_frequency=fields.get("cache_frequency", row["cache_frequency"]),
                        sql=sql, step_params=step_params, data_source=data_source,
                    )
                    if errors:
                        raise InvalidAnalysisDefinitionError(errors)

                await self._analyses.update(analysis_id, fields, tx)  # sempre atualiza updated_at
                if step_patch is not None:
                    definition = {"sql": sql, "params": step_params}
                    if current is None:
                        await self._analyses.create_step(analysis_id, definition, tx)
                    else:
                        await self._analyses.update_step(current.id, definition, tx)
        except asyncpg.UniqueViolationError as exc:
            raise AnalysisNameAlreadyExistsError() from exc
        log_admin_action(actor.id, "update_analysis", "analysis", analysis_id)
        return await self._detail(analysis_id)

    async def delete_analysis(self, analysis_id: UUID, actor: AuthenticatedUser) -> None:
        try:
            async with self._db.transaction() as tx:
                if await self._analyses.get_admin_row(analysis_id, tx) is None:
                    raise AdminAnalysisNotFoundError()
                if await self._analyses.has_history(analysis_id, tx):
                    raise AnalysisHasHistoryError()
                await self._analyses.delete(analysis_id, tx)
        except asyncpg.ForeignKeyViolationError as exc:
            raise AnalysisHasHistoryError() from exc
        log_admin_action(actor.id, "delete_analysis", "analysis", analysis_id)

    async def set_profiles(
        self, analysis_id: UUID, profile_ids: list[UUID], actor: AuthenticatedUser
    ) -> AnalysisDetail:
        """Não altera `updated_at`: permissão não entra na chave do cache (F24 decisão 11)."""
        profile_ids = list(dict.fromkeys(profile_ids))
        async with self._db.transaction() as tx:
            if await self._analyses.get_admin_row(analysis_id, tx) is None:
                raise AdminAnalysisNotFoundError()
            await self._check_profiles_exist(profile_ids, tx)
            await self._analyses.replace_profiles(analysis_id, profile_ids, tx)
        log_admin_action(actor.id, "set_analysis_profiles", "analysis", analysis_id)
        return await self._detail(analysis_id)

    async def validate(self, analysis_id: UUID) -> ValidationReport:
        """Só estático: não conecta ao data source (F24 decisão 3)."""
        row = await self._analyses.get_admin_row(analysis_id)
        if row is None:
            raise AdminAnalysisNotFoundError()
        steps = await self._analyses.get_steps(analysis_id)
        step = steps[0] if steps else None
        data_source = (
            await self._data_sources.get_by_id(row["data_source_id"]) if row["data_source_id"] else None
        )
        errors, warnings = validate_analysis_definition(
            parameters=row["parameters"], cache_frequency=row["cache_frequency"],
            sql=step.definition.get("sql") if step else None,
            step_params=list(step.definition.get("params") or []) if step else None,
            data_source=data_source,
        )
        return ValidationReport(valid=not errors, errors=errors, warnings=warnings)

    async def invalidate_cache(self, analysis_id: UUID, actor: AuthenticatedUser) -> InvalidateResult:
        """`updated_at = NOW()`: as chaves antigas ficam inalcançáveis e saem por TTL/LRU."""
        updated_at = await self._analyses.touch(analysis_id)
        if updated_at is None:
            raise AdminAnalysisNotFoundError()
        log_admin_action(actor.id, "invalidate_cache", "analysis", analysis_id)
        return InvalidateResult(invalidated=True, updated_at=updated_at)
