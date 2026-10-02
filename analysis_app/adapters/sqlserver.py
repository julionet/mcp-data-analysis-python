"""Adapter SQL Server (aioodbc + pyodbc) — F11_SQLSERVER_ADAPTER.md §4.4.

Fluxo de placeholders: ``translate_params`` gera ``@nome`` (nomeado, como o T-SQL);
``execute_query`` converte ``@nome`` → ``?`` na ordem de ocorrência, porque o
pyodbc só aceita parâmetros posicionais (F11 §3, Opção 1A).
"""

import re

import aioodbc

from adapters.base import DatabaseAdapter
from config import settings

DEFAULT_DRIVER = "ODBC Driver 18 for SQL Server"
DEFAULT_PORT = 1433
DEFAULT_SSLMODE = "prefer"

# sslmode → trecho da connection string ODBC (F11 §4.4)
_SSLMODE_TO_ODBC = {
    "disable": "Encrypt=no",
    "prefer": "Encrypt=yes;TrustServerCertificate=yes",
    "verify-full": "Encrypt=yes;TrustServerCertificate=no",
}

# Erros nativos do wrapper SELECT COUNT(*) FROM (<sql>) sub (F11 §8.4):
# 1033 = ORDER BY em subquery, 8155 = coluna sem nome, 8156 = coluna duplicada.
_RESTRICTED_SQL_ERRORS = ("(1033)", "(8155)", "(8156)")
_ORDER_BY_TEXT = "ORDER BY clause is invalid in views, inline functions, derived tables, subqueries"

_PLACEHOLDER_RE = re.compile(r"(?<![@\w])@(\w+)")


class SQLServerAdapter(DatabaseAdapter):
    def _build_connection_string(self) -> str:
        """Monta a connection string ODBC (só usuário/senha, sem Integrated Auth).

        Levanta ValueError se ``sslmode`` estiver fora de ``_SSLMODE_TO_ODBC``.
        """
        sslmode = self.config.get("sslmode", DEFAULT_SSLMODE)
        ssl_part = _SSLMODE_TO_ODBC.get(sslmode)
        if ssl_part is None:
            raise ValueError(f"sslmode '{sslmode}' não suportado para sqlserver")

        driver = self.config.get("driver", DEFAULT_DRIVER)
        port = self.config.get("port", DEFAULT_PORT)
        # Senha entre chaves; '}' vira '}}' (suporta ';' e '}' na senha)
        password = "{" + str(self.config["password"]).replace("}", "}}") + "}"
        return (
            f"DRIVER={{{driver}}};"
            f"SERVER={self.config['host']},{port};"
            f"DATABASE={self.config['database']};"
            f"UID={self.config['user']};"
            f"PWD={password};"
            f"{ssl_part}"
        )

    async def connect(self) -> None:
        """Abre o pool aioodbc (minsize=1, maxsize=10; o default do aioodbc é 10/10)."""
        dsn = self._build_connection_string()  # fail-fast antes de abrir o pool
        self._pool = await aioodbc.create_pool(
            dsn=dsn,
            minsize=1,
            maxsize=10,
            autocommit=True,
            timeout=settings.query_timeout_seconds,
        )

    async def disconnect(self) -> None:
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()

    @staticmethod
    def _to_positional(sql: str, params: dict | None) -> tuple[str, list]:
        """Converte ``@nome`` → ``?`` e devolve os valores na ordem de ocorrência.

        Só substitui nomes presentes em ``params`` (``@@ROWCOUNT`` e variáveis locais
        ficam intactos). Parâmetro repetido gera valor repetido.
        """
        params = params or {}
        values: list = []

        def replace(match: re.Match) -> str:
            name = match.group(1)
            if name not in params:
                return match.group(0)
            values.append(params[name])
            return "?"

        return _PLACEHOLDER_RE.sub(replace, sql), values

    async def execute_query(self, query: str, params: dict | None = None, scalar: bool = False):
        """Converte @nome → ? (ordem de ocorrência) e executa.

        scalar=True retorna a primeira coluna da primeira linha (None se vazio);
        scalar=False retorna list[dict] com as chaves de cursor.description.
        Erros de SQL fora do subconjunto comum (§8.4) são relançados com mensagem
        explicativa.
        """
        sql, values = self._to_positional(query, params)
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute(sql, *values)
                except Exception as exc:
                    if self._is_restricted_sql_error(exc):
                        raise RuntimeError(
                            "SQL fora do subconjunto comum suportado no SQL Server "
                            "(sem ORDER BY de topo sem TOP/OFFSET; toda coluna do SELECT "
                            "com nome único e explícito) — ver F11 §8.4. "
                            f"Erro original: {exc}"
                        ) from exc
                    raise
                if scalar:
                    row = await cursor.fetchone()
                    return row[0] if row else None
                columns = [col[0] for col in cursor.description]
                rows = await cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]

    @staticmethod
    def _is_restricted_sql_error(exc: Exception) -> bool:
        message = str(exc)
        return any(code in message for code in _RESTRICTED_SQL_ERRORS) or _ORDER_BY_TEXT in message

    async def execute(self, query: str, *args) -> None:
        """Executa INSERT/UPDATE/DELETE com parâmetros posicionais (?), autocommit."""
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, *args)

    async def test_connection(self) -> bool:
        try:
            await self.execute_query("SELECT 1")
            return True
        except Exception:
            return False

    def translate_params(self, sql: str, param_names: list[str]) -> str:
        """Traduz placeholders nomeados (:param) para T-SQL (@param).

        Exemplo:
            input:  "SELECT * FROM t WHERE x = :x AND y = :y", ["x", "y"]
            output: "SELECT * FROM t WHERE x = @x AND y = @y"
        """
        translated = sql
        for name in param_names:
            translated = re.sub(rf":{re.escape(name)}\b", f"@{name}", translated)
        return translated
