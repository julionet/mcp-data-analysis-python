"""Acesso a analyses/analysis_steps no Config DB — ARQUITETURA.md §2.2/§4.1,
F4_EXECUTION_ENGINE.md §4.4.

O asyncpg não decodifica colunas JSONB automaticamente (nenhum type codec
registrado em adapters/postgresql.py) — chegam como `str`, daí o
`_load_json` defensivo abaixo.

F7 (ajuste retroativo): Analysis passa a trazer updated_at e cache_frequency,
consumidos por CacheService (chave e TTL) — ver F7_CACHE_SERVICE.md §4.2.
TIMESTAMP é decodificado nativamente pelo asyncpg como datetime, sem passar
por _load_json.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from adapters.postgresql import PostgreSQLAdapter
from repositories.sql_helpers import like_pattern

_ADMIN_COLUMNS = (
    "a.id, a.name, a.description, a.data_source_id, ds.name AS data_source_name, "
    "a.cache_frequency, a.is_active, a.created_by, a.created_at, a.updated_at, "
    "(SELECT COUNT(*) FROM profile_analyses pa WHERE pa.analysis_id = a.id) AS profiles_count"
)
_ADMIN_FROM = "FROM analyses a LEFT JOIN data_sources ds ON ds.id = a.data_source_id"
_ADMIN_FILTERS = (
    "WHERE ($1::text IS NULL OR a.name ILIKE $1 ESCAPE '\\' OR a.description ILIKE $1 ESCAPE '\\') "
    "AND ($2::uuid IS NULL OR a.data_source_id = $2) "
    "AND ($3::bool IS NULL OR a.is_active = $3)"
)


def _load_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


@dataclass
class Analysis:
    id: UUID
    name: str
    description: str | None
    data_source_id: UUID
    parameters: dict[str, Any]
    is_active: bool
    updated_at: datetime
    cache_frequency: str


@dataclass
class AnalysisStep:
    id: UUID
    analysis_id: UUID
    step_order: int
    step_type: str
    definition: dict[str, Any]


def _to_analysis(row: dict) -> Analysis:
    return Analysis(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        data_source_id=row["data_source_id"],
        parameters=_load_json(row["parameters"]) or {},
        is_active=row["is_active"],
        updated_at=row["updated_at"],
        cache_frequency=row["cache_frequency"],
    )


def _to_step(row: dict) -> AnalysisStep:
    return AnalysisStep(
        id=row["id"],
        analysis_id=row["analysis_id"],
        step_order=row["step_order"],
        step_type=row["step_type"],
        definition=_load_json(row["definition"]) or {},
    )


class AnalysisRepository:
    def __init__(self, config_db_adapter: PostgreSQLAdapter) -> None:
        self._db = config_db_adapter

    async def get_by_id(self, analysis_id: UUID) -> Analysis | None:
        """Retorna None se a análise não existir ou estiver inativa
        (AnalysisService converte isso em AnalysisNotFoundError)."""
        rows = await self._db.execute_query(
            "SELECT id, name, description, data_source_id, parameters, is_active, "
            "updated_at, cache_frequency "
            "FROM analyses WHERE id = $1 AND is_active = true",
            {"id": analysis_id},
        )
        return _to_analysis(rows[0]) if rows else None

    async def get_by_name(self, name: str) -> Analysis | None:
        """Busca uma análise ativa OU inativa pelo nome único (analyses.name).
        Usada por call_tool() (F5) a cada execução — sem cache, para refletir
        imediatamente qualquer mudança feita no banco (ativação/desativação/
        rename). Ao contrário de get_by_id(), não filtra por is_active: quem
        chama precisa distinguir "não encontrada" de "inativa" (F5_MCP_TOOLS_
        INTEGRATION.md §4.2 Fluxo B, passo 4)."""
        rows = await self._db.execute_query(
            "SELECT id, name, description, data_source_id, parameters, is_active, "
            "updated_at, cache_frequency "
            "FROM analyses WHERE name = $1",
            {"name": name},
        )
        return _to_analysis(rows[0]) if rows else None

    async def get_all(self) -> list[Analysis]:
        rows = await self._db.execute_query(
            "SELECT id, name, description, data_source_id, parameters, is_active, "
            "updated_at, cache_frequency "
            "FROM analyses WHERE is_active = true"
        )
        return [_to_analysis(row) for row in rows]

    async def get_allowed_for_user(self, user_id: UUID) -> list[Analysis]:
        """F12: analyses ativas vinculadas a um perfil ativo vinculado ao usuário.
        Mesma regra de ProfileRepository.get_allowed_analysis_ids() (usada na
        revalidação de call_tool()); um teste de integração garante que concordam."""
        rows = await self._db.execute_query(
            "SELECT DISTINCT a.id, a.name, a.description, a.data_source_id, a.parameters, "
            "a.is_active, a.updated_at, a.cache_frequency "
            "FROM analyses a "
            "JOIN profile_analyses pa ON pa.analysis_id = a.id "
            "JOIN user_profiles up ON up.profile_id = pa.profile_id "
            "JOIN profiles p ON p.id = pa.profile_id "
            "WHERE up.user_id = $1 AND a.is_active = true AND p.is_active = true",
            {"user_id": user_id},
        )
        return [_to_analysis(row) for row in rows]

    async def get_steps(self, analysis_id: UUID, db=None) -> list[AnalysisStep]:
        rows = await (db or self._db).execute_query(
            "SELECT id, analysis_id, step_order, step_type, definition "
            "FROM analysis_steps WHERE analysis_id = $1 ORDER BY step_order",
            {"analysis_id": analysis_id},
        )
        return [_to_step(row) for row in rows]

    # ---- F24: administração (inclui inativas; aceitam `db` opcional: adapter ou Transaction) ----

    async def admin_list(
        self, q: str | None, data_source_id: UUID | None, is_active: bool | None,
        limit: int, offset: int,
    ) -> tuple[list[dict], int]:
        filters = {"q": like_pattern(q), "data_source_id": data_source_id, "is_active": is_active}
        total = await self._db.execute_query(
            f"SELECT COUNT(*) {_ADMIN_FROM} {_ADMIN_FILTERS}", filters, scalar=True
        )
        rows = await self._db.execute_query(
            f"SELECT {_ADMIN_COLUMNS} {_ADMIN_FROM} {_ADMIN_FILTERS} "
            "ORDER BY a.name, a.id LIMIT $4 OFFSET $5",
            {**filters, "limit": limit, "offset": offset},
        )
        return rows, total

    async def get_admin_row(self, analysis_id: UUID, db=None) -> dict | None:
        """Resumo + `parameters` (decodificado), ativa ou inativa."""
        rows = await (db or self._db).execute_query(
            f"SELECT {_ADMIN_COLUMNS}, a.parameters {_ADMIN_FROM} WHERE a.id = $1",
            {"id": analysis_id},
        )
        if not rows:
            return None
        row = rows[0]
        row["parameters"] = _load_json(row["parameters"]) or {}
        return row

    async def get_profiles(self, analysis_id: UUID, db=None) -> list[dict]:
        return await (db or self._db).execute_query(
            "SELECT p.id, p.name, p.is_active FROM profiles p "
            "JOIN profile_analyses pa ON pa.profile_id = p.id WHERE pa.analysis_id = $1 "
            "ORDER BY p.name, p.id",
            {"analysis_id": analysis_id},
        )

    async def create(self, fields: dict, db=None) -> UUID:
        """`fields`: name, description, data_source_id, cache_frequency, parameters, is_active, created_by."""
        return await (db or self._db).execute_query(
            "INSERT INTO analyses (name, description, data_source_id, cache_frequency, "
            "parameters, is_active, created_by) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7) RETURNING id",
            {**fields, "parameters": json.dumps(fields["parameters"])},
            scalar=True,
        )

    async def create_step(self, analysis_id: UUID, definition: dict, db=None) -> UUID:
        return await (db or self._db).execute_query(
            "INSERT INTO analysis_steps (analysis_id, step_order, step_type, definition) "
            "VALUES ($1, 1, 'query', $2::jsonb) RETURNING id",
            {"analysis_id": analysis_id, "definition": json.dumps(definition)},
            scalar=True,
        )

    async def update_step(self, step_id: UUID, definition: dict, db=None) -> None:
        await (db or self._db).execute_query(
            "UPDATE analysis_steps SET definition = $2::jsonb, updated_at = NOW() "
            "WHERE id = $1 RETURNING id",
            {"id": step_id, "definition": json.dumps(definition)},
        )

    async def update(self, analysis_id: UUID, fields: dict, db=None) -> bool:
        """`updated_at = NOW()` SEMPRE (entra na chave do cache — F7); `fields` pode ser vazio."""
        values = {k: (json.dumps(v) if k == "parameters" else v) for k, v in fields.items()}
        parts = [
            f"{col} = ${i}::jsonb" if col == "parameters" else f"{col} = ${i}"
            for i, col in enumerate(values, start=2)
        ]
        rows = await (db or self._db).execute_query(
            f"UPDATE analyses SET {', '.join(parts + ['updated_at = NOW()'])} "
            "WHERE id = $1 RETURNING id",
            {"id": analysis_id, **values},
        )
        return bool(rows)

    async def touch(self, analysis_id: UUID, db=None):
        """Invalidação de cache: devolve o novo updated_at, ou None se a análise não existe."""
        return await (db or self._db).execute_query(
            "UPDATE analyses SET updated_at = NOW() WHERE id = $1 RETURNING updated_at",
            {"id": analysis_id},
            scalar=True,
        )

    async def has_history(self, analysis_id: UUID, db=None) -> bool:
        return bool(
            await (db or self._db).execute_query(
                "SELECT 1 FROM execution_history WHERE analysis_id = $1 LIMIT 1",
                {"analysis_id": analysis_id},
                scalar=True,
            )
        )

    async def delete(self, analysis_id: UUID, db=None) -> bool:
        """Físico: analysis_steps e profile_analyses caem em cascata."""
        rows = await (db or self._db).execute_query(
            "DELETE FROM analyses WHERE id = $1 RETURNING id", {"id": analysis_id}
        )
        return bool(rows)

    async def replace_profiles(self, analysis_id: UUID, profile_ids: list[UUID], db) -> None:
        await db.execute("DELETE FROM profile_analyses WHERE analysis_id = $1", analysis_id)
        if profile_ids:
            await db.execute(
                "INSERT INTO profile_analyses (analysis_id, profile_id) SELECT $1, UNNEST($2::uuid[])",
                analysis_id,
                profile_ids,
            )
