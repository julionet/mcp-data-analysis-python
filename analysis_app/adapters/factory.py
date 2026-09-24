"""Factory Pattern de adapters de data source — ARQUITETURA.md §4.2,
F4_EXECUTION_ENGINE.md §4.4."""

from typing import Type

from adapters.base import DatabaseAdapter
from adapters.postgresql import PostgreSQLAdapter


class AdapterFactory:
    _adapters: dict[str, Type[DatabaseAdapter]] = {
        "postgresql": PostgreSQLAdapter,
        # demais tipos entram no Sprint 2 (F11 MongoDB, F12 MySQL, F13 SQL Server)
    }

    @classmethod
    def create_adapter(cls, source_type: str, config: dict) -> DatabaseAdapter:
        """Levanta ValueError com mensagem clara se source_type não estiver
        registrado (ex.: 'mongodb' antes do F11)."""
        adapter_cls = cls._adapters.get(source_type)
        if adapter_cls is None:
            raise ValueError(
                f"Tipo de data source '{source_type}' não suportado. "
                f"Tipos disponíveis: {sorted(cls._adapters)}"
            )
        return adapter_cls(config)
