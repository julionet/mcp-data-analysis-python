"""Regras de administração de data sources — F24 §4.4.

A senha do `connection_config` é cifrada (Fernet) ao gravar e NUNCA devolvida, logada nem
incluída em mensagem de erro. Editar/desativar/excluir um data source derruba o pool em
`AnalysisService._adapters` (`pool_invalidator`) e atualiza o `updated_at` das analyses dele
(o cache não conhece o data source).
"""

import asyncio
import logging
import time
from typing import Any
from uuid import UUID

import asyncpg
from cryptography.fernet import InvalidToken

from adapters.factory import AdapterFactory
from repositories.data_source_repo import DataSourceRepository
from repositories.user_repo import UserRepository
from schemas.admin import (
    ConnectionTestBody,
    ConnectionTestResult,
    DataSourceAnalysisRef,
    DataSourceCreate,
    DataSourceDetail,
    DataSourceHasAnalysesError,
    DataSourceNameAlreadyExistsError,
    DataSourceNotFoundError,
    DataSourceSummary,
    DataSourceTypeInfo,
    DataSourceUpdate,
    InvalidConnectionConfigError,
    Page,
)
from schemas.auth import AuthenticatedUser
from schemas.data_source_types import DATA_SOURCE_TYPES, get_type, validate_connection_config
from security.crypto import decrypt_password, encrypt_password
from services.user_admin_service import log_admin_action

logger = logging.getLogger(__name__)

TEST_CONNECTION_TIMEOUT_SECONDS = 10


class DataSourceAdminService:
    def __init__(
        self, db, repo: DataSourceRepository, pool_invalidator, users: UserRepository
    ) -> None:
        self._db = db
        self._repo = repo
        self._pool = pool_invalidator  # objeto com `async invalidate_data_source(id)`
        self._users = users

    async def _detail(self, ds_id: UUID, db=None) -> DataSourceDetail:
        summary = await self._repo.get_summary(ds_id, db)
        if summary is None:
            raise DataSourceNotFoundError()
        source = await self._repo.get_by_id(ds_id, db)
        config = dict(source.connection_config)
        has_password = bool(config.pop("password", None))
        analyses = await self._repo.get_analyses(ds_id, db)
        return DataSourceDetail(
            **summary, connection_config=config, has_password=has_password,
            analyses=[DataSourceAnalysisRef(**a) for a in analyses],
        )

    async def _invalidate_pool(self, ds_id: UUID) -> None:
        try:
            await self._pool.invalidate_data_source(ds_id)
        except Exception:
            logger.exception("Falha ao invalidar o pool do data source '%s'", ds_id)

    # ---- leitura ----

    async def list_types(self) -> list[DataSourceTypeInfo]:
        return [
            DataSourceTypeInfo(
                type=t.type,
                required=list(t.required),
                optional=[{"name": k, "default": v} for k, v in t.optional.items()],
                one_of=[list(g) for g in t.one_of],
            )
            for t in DATA_SOURCE_TYPES.values()
        ]

    async def list_data_sources(
        self, q: str | None, type_: str | None, is_active: bool | None, limit: int, offset: int
    ) -> Page[DataSourceSummary]:
        rows, total = await self._repo.list_page(q, type_, is_active, limit, offset)
        return Page[DataSourceSummary](
            items=[DataSourceSummary(**r) for r in rows], total=total, limit=limit, offset=offset
        )

    async def get_data_source(self, ds_id: UUID) -> DataSourceDetail:
        return await self._detail(ds_id)

    # ---- escrita ----

    async def create_data_source(
        self, data: DataSourceCreate, actor: AuthenticatedUser
    ) -> DataSourceDetail:
        validate_connection_config(data.type, data.connection_config)
        stored = {**data.connection_config, "password": encrypt_password(data.connection_config["password"])}
        actor_row = await self._users.get_by_id(actor.id)
        try:
            ds_id = await self._repo.create(
                data.name, data.type, stored, data.is_active,
                actor_row.external_id if actor_row else None,
            )
        except asyncpg.UniqueViolationError as exc:
            raise DataSourceNameAlreadyExistsError() from exc
        log_admin_action(actor.id, "create_data_source", "data_source", ds_id)
        return await self._detail(ds_id)

    def _merge_config(self, type_: str, current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        """Chaves enviadas substituem; omitidas permanecem; null remove uma opcional.
        `password` só é recifrada se enviada (a cifra salva é preservada sem ser decifrada)."""
        spec = get_type(type_)
        merged = dict(current)
        for key, value in patch.items():
            if key not in spec.allowed:
                raise InvalidConnectionConfigError(
                    f"connection_config inválido: chave desconhecida para '{type_}': {key}."
                )
            if value is None:
                if key in spec.required:
                    raise InvalidConnectionConfigError(
                        f"connection_config inválido: '{key}' é obrigatório e não pode ser removido."
                    )
                merged.pop(key, None)
            elif key == "password":
                if not (isinstance(value, str) and value):
                    raise InvalidConnectionConfigError(
                        "connection_config inválido: 'password' deve ser um texto não vazio."
                    )
                merged[key] = encrypt_password(value)
            else:
                merged[key] = value
        validate_connection_config(type_, merged)
        return merged

    async def update_data_source(
        self, ds_id: UUID, data: DataSourceUpdate, actor: AuthenticatedUser
    ) -> DataSourceDetail:
        sent = data.model_fields_set
        fields: dict[str, Any] = {}
        if "name" in sent and data.name is not None:
            fields["name"] = data.name
        if "is_active" in sent and data.is_active is not None:
            fields["is_active"] = data.is_active
        connection_changed = False
        try:
            async with self._db.transaction() as tx:
                current = await self._repo.get_by_id(ds_id, tx)
                if current is None:
                    raise DataSourceNotFoundError()
                if "connection_config" in sent and data.connection_config is not None:
                    merged = self._merge_config(current.type, current.connection_config, data.connection_config)
                    if merged != current.connection_config:
                        fields["connection_config"] = merged
                        connection_changed = True
                active_changed = "is_active" in fields and fields["is_active"] != current.is_active
                if fields:
                    await self._repo.update(ds_id, fields, tx)
                if connection_changed or active_changed:
                    await self._repo.touch_analyses(ds_id, tx)
        except asyncpg.UniqueViolationError as exc:
            raise DataSourceNameAlreadyExistsError() from exc
        if connection_changed or active_changed:
            await self._invalidate_pool(ds_id)
        log_admin_action(actor.id, "update_data_source", "data_source", ds_id)
        return await self._detail(ds_id)

    async def delete_data_source(self, ds_id: UUID, actor: AuthenticatedUser) -> None:
        try:
            async with self._db.transaction() as tx:
                summary = await self._repo.get_summary(ds_id, tx)
                if summary is None:
                    raise DataSourceNotFoundError()
                if summary["analyses_count"] > 0:
                    raise DataSourceHasAnalysesError()
                await self._repo.delete(ds_id, tx)
        except asyncpg.ForeignKeyViolationError as exc:
            raise DataSourceHasAnalysesError() from exc
        await self._invalidate_pool(ds_id)
        log_admin_action(actor.id, "delete_data_source", "data_source", ds_id)

    # ---- teste de conexão ----

    async def test_saved(self, ds_id: UUID) -> ConnectionTestResult:
        source = await self._repo.get_by_id(ds_id)
        if source is None:
            raise DataSourceNotFoundError()
        config = dict(source.connection_config)
        try:
            config["password"] = decrypt_password(config["password"])
        except (InvalidToken, KeyError, ValueError, TypeError):
            return ConnectionTestResult(
                ok=False, error_type="InvalidToken", elapsed_ms=0,
                message="A senha armazenada não pôde ser decifrada (FERNET_KEY diferente da usada no cadastro?).",
            )
        return await self._probe(source.type, config)

    async def test_config(self, data: ConnectionTestBody) -> ConnectionTestResult:
        validate_connection_config(data.type, data.connection_config)
        return await self._probe(data.type, dict(data.connection_config))

    async def _probe(self, type_: str, config: dict[str, Any]) -> ConnectionTestResult:
        """Adapter temporário (nunca o pool do AnalysisService), sem retry, com limite de tempo.
        A falha é parte do resultado (200); o texto da exceção do driver não é devolvido."""
        started = time.perf_counter()
        adapter = None

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        try:
            adapter = AdapterFactory.create_adapter(type_, config)

            async def run() -> bool:
                await adapter.connect()
                return await adapter.test_connection()

            ok = await asyncio.wait_for(run(), TEST_CONNECTION_TIMEOUT_SECONDS)
            if ok:
                return ConnectionTestResult(ok=True, message="Conexão estabelecida com sucesso.", elapsed_ms=elapsed())
            return ConnectionTestResult(
                ok=False, elapsed_ms=elapsed(),
                message="A conexão foi aberta, mas a consulta de teste falhou.",
            )
        except Exception as exc:
            logger.warning(
                "test_connection falhou type=%s error_type=%s detail=%s",
                type_, type(exc).__name__, str(exc).replace(config.get("password") or "\0", "***"),
            )
            if isinstance(exc, TimeoutError) or (adapter and adapter.is_timeout_error(exc)):
                message = f"Tempo esgotado ao conectar (limite de {TEST_CONNECTION_TIMEOUT_SECONDS} s)."
            elif adapter and adapter.is_transient_error(exc):
                message = "Falha de conexão com o servidor do banco (recusada, reiniciada ou indisponível)."
            else:
                message = "Não foi possível conectar ou consultar o banco (credenciais, banco ou configuração incorretos)."
            return ConnectionTestResult(
                ok=False, message=message, error_type=type(exc).__name__, elapsed_ms=elapsed()
            )
        finally:
            if adapter is not None:
                try:
                    await adapter.disconnect()
                except Exception:
                    logger.debug("Falha ao fechar o adapter do teste de conexão", exc_info=True)
