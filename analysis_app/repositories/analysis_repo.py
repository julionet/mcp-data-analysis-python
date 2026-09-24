"""Acesso a analyses/analysis_steps no Config DB — ARQUITETURA.md §2.2/§4.1,
F4_EXECUTION_ENGINE.md §4.4.

O asyncpg não decodifica colunas JSONB automaticamente (nenhum type codec
registrado em adapters/postgresql.py) — chegam como `str`, daí o
`_load_json` defensivo abaixo.
"""

import json
from dataclasses import dataclass
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
            "SELECT id, name, description, data_source_id, parameters, is_active "
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
            "SELECT id, name, description, data_source_id, parameters, is_active "
            "FROM analyses WHERE name = $1",
            {"name": name},
        )
        return _to_analysis(rows[0]) if rows else None

    async def get_all(self) -> list[Analysis]:
        rows = await self._db.execute_query(
            "SELECT id, name, description, data_source_id, parameters, is_active "
            "FROM analyses WHERE is_active = true"
        )
        return [_to_analysis(row) for row in rows]

    async def get_steps(self, analysis_id: UUID) -> list[AnalysisStep]:
        rows = await self._db.execute_query(
            "SELECT id, analysis_id, step_order, step_type, definition "
            "FROM analysis_steps WHERE analysis_id = $1 ORDER BY step_order",
            {"analysis_id": analysis_id},
        )
        return [_to_step(row) for row in rows]
