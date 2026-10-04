"""Interface abstrata de acesso a banco de dados (Factory Pattern, ARQUITETURA.md §4.2).

Base para todos os adapters de data source (PostgreSQL, MySQL e,
SQL Server e Oracle).
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
    async def execute_query(self, query: str, params: dict | None = None, scalar: bool = False):
        """Executa query parametrizada e retorna resultado normalizado.

        scalar=True retorna um único valor escalar (ex: COUNT(*)); scalar=False
        (padrão) retorna list[dict], uma linha por dict.
        """

    @abstractmethod
    async def execute(self, query: str, *args) -> None:
        """Executa comando INSERT/UPDATE/DELETE parametrizado."""

    @abstractmethod
    async def test_connection(self) -> bool:
        """Usado pelo /health e por validações de data_source."""

    def is_timeout_error(self, exc: Exception) -> bool:
        """F14: True se `exc` é o estouro do timeout de QUERY (QUERY_TIMEOUT_SECONDS) deste driver.

        Não-abstrato: um adapter sem override nunca classifica timeout (default False).
        """
        return False

    def is_transient_error(self, exc: Exception) -> bool:
        """F14: True se `exc` é uma falha de CONEXÃO rápida e repetível (recusada, resetada,
        perdida, limite de conexões) — a única classe que recebe retry automático.

        Timeouts (de query OU de conexão) ficam de fora: repetir uma espera de 30 s três
        vezes passaria do limite de tempo (F14 decisão 8). Credencial inválida e erro de
        SQL também não são transitórios. Default False.
        """
        return False

    @abstractmethod
    def translate_params(self, sql: str, param_names: list[str]) -> str:
        """Traduz placeholders nomeados (:param) para o formato posicional do banco.

        Exemplos:
        - PostgreSQL: :data_inicial → $1, :data_final → $2
        - MySQL: :data_inicial → %(data_inicial)s, :data_final → %(data_final)s
        - SQL Server: :data_inicial → @data_inicial (convertido para ? na execução)
        - Oracle: :data_inicial → :p1, :data_final → :p2 (índice em param_names)
        """
