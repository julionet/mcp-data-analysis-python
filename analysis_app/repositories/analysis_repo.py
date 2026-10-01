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

    async def get_steps(self, analysis_id: UUID) -> list[AnalysisStep]:
        rows = await self._db.execute_query(
            "SELECT id, analysis_id, step_order, step_type, definition "
            "FROM analysis_steps WHERE analysis_id = $1 ORDER BY step_order",
            {"analysis_id": analysis_id},
        )
        return [_to_step(row) for row in rows]
