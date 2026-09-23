"""Interface abstrata de acesso a banco de dados (Factory Pattern, ARQUITETURA.md §4.2).

Base para todos os adapters de data source (PostgreSQL, e futuramente
MySQL, SQL Server, MongoDB).
"""

from abc import ABC, abstractmethod


class DatabaseAdapter(ABC):
    def __init__(self, config: dict) -> None:
        self.config = config
        self._pool = None

    @abstractmethod
    async def connect(self) -> None:
        """Abre o pool de conexões."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Fecha o pool de conexões."""

    @abstractmethod
    async def execute_query(self, query: str, params: dict | None = None) -> list[dict]:
        """Executa query parametrizada e retorna resultado normalizado."""

    @abstractmethod
    async def test_connection(self) -> bool:
        """Usado pelo /health e por validações de data_source."""
