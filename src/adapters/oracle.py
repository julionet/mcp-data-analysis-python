"""Adapter Oracle (python-oracledb, thin mode, async) — F9_ORACLE_ADAPTER.md §4.4.

Fluxo de placeholders: ``translate_params`` converte ``:nome`` em ``:pN`` (N = índice do
nome em ``param_names``, base 1 — evita nome de bind reservado, ORA-01745); em
``execute_query`` o n-ésimo valor de ``params`` é ligado a ``pN``. Como no PostgreSQL,
isso exige que ``params`` chegue na ordem de ``param_names`` (``ordered_values`` do
``analysis_service``).
"""

import re

import oracledb

from adapters.base import DatabaseAdapter
from config import settings

DEFAULT_PORT = 1521

# Erros nativos do wrapper SELECT COUNT(*) FROM (<sql>) sub (F9 §8.4):
# ORA-00911 = caractere inválido (';' no fim do SQL), ORA-00918 = coluna ambígua/duplicada.
_RESTRICTED_SQL_ERRORS = ("ORA-00911", "ORA-00918")

_PLACEHOLDER_RE = re.compile(r"(?<![\w:]):(\w+)")

_TIMEOUT_CODES = {"DPY-4024", "ORA-03156"}
# DPY-4011 conexão fechada pelo banco/rede; ORA-03113/03114 fim de arquivo/não conectado;
# ORA-12541 sem listener; ORA-01033/01089 banco subindo/desligando
_TRANSIENT_CODES = {"DPY-4011", "ORA-03113", "ORA-03114", "ORA-12541", "ORA-01033", "ORA-01089"}


class OracleAdapter(DatabaseAdapter):
    def _build_dsn(self) -> str:
        """Monta o DSN (``oracledb.makedsn``) a partir de host, port, service_name | sid.

        Levanta ValueError se ``service_name`` e ``sid`` vierem juntos ou ambos ausentes.
        """
        service_name = self.config.get("service_name")
        sid = self.config.get("sid")
        if bool(service_name) == bool(sid):
            raise ValueError("Oracle exige exatamente um entre 'service_name' e 'sid'")

        port = self.config.get("port", DEFAULT_PORT)
        if service_name:
            return oracledb.makedsn(self.config["host"], port, service_name=service_name)
        return oracledb.makedsn(self.config["host"], port, sid=sid)

    async def connect(self) -> None:
        """Abre o pool async (min=1, max=10) e valida uma conexão (fail-fast).

        ``create_pool_async`` é preguiçoso: sem o ``acquire`` abaixo, credencial inválida
        só apareceria na primeira análise.
        """
        dsn = self._build_dsn()  # fail-fast antes de abrir o pool
        pool = oracledb.create_pool_async(
            user=self.config["user"],
            password=self.config["password"],
            dsn=dsn,
            min=1,
            max=10,
            tcp_connect_timeout=settings.query_timeout_seconds,
        )
        try:
            async with pool.acquire():
                pass
        except Exception:
            await pool.close(force=True)
            raise
        self._pool = pool

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()

    @staticmethod
    def _to_binds(params: dict | None) -> dict:
        """n-ésimo valor de ``params`` → ``pN`` (contrato do ``translate_params``)."""
        return {f"p{i}": value for i, value in enumerate((params or {}).values(), 1)}

    async def execute_query(self, query: str, params: dict | None = None, scalar: bool = False):
        """Liga ``:pN`` ← ``params.values()`` e executa.

        scalar=True retorna a primeira coluna da primeira linha (None se vazio);
        scalar=False retorna list[dict] com chaves em minúsculas (Oracle devolve
        MAIÚSCULAS). CLOB/BLOB voltam como str/bytes e NUMBER como Decimal.
        Erros de SQL fora do subconjunto comum (§8.4) são relançados com mensagem
        explicativa.
        """
        async with self._pool.acquire() as conn:
            conn.call_timeout = settings.query_timeout_seconds * 1000  # ms
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute(
                        query, self._to_binds(params), fetch_lobs=False, fetch_decimals=True
                    )
                except Exception as exc:
                    if self._is_restricted_sql_error(exc):
                        raise RuntimeError(
                            "SQL fora do subconjunto comum suportado no Oracle (sem ';' no "
                            "fim do SQL; toda coluna do SELECT com nome único e explícito) "
                            f"— ver F9 §8.4. Erro original: {exc}"
                        ) from exc
                    raise
                if scalar:
                    row = await cursor.fetchone()
                    return row[0] if row else None
                columns = [col[0].lower() for col in cursor.description]
                rows = await cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]

    @staticmethod
    def _is_restricted_sql_error(exc: Exception) -> bool:
        message = str(exc)
        return any(code in message for code in _RESTRICTED_SQL_ERRORS)

    async def execute(self, query: str, *args) -> None:
        """Executa INSERT/UPDATE/DELETE com binds posicionais (:1, :2...) e commit explícito."""
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, list(args))
            await conn.commit()

    async def test_connection(self) -> bool:
        """``SELECT 1 FROM DUAL`` (Oracle exige FROM; só o 23ai dispensa)."""
        try:
            await self.execute_query("SELECT 1 FROM DUAL")
            return True
        except Exception:
            return False

    @staticmethod
    def _full_code(exc: Exception) -> str | None:
        """Código completo ("DPY-4024", "ORA-03113") de um oracledb.Error — args[0].full_code."""
        if isinstance(exc, oracledb.Error) and exc.args:
            return getattr(exc.args[0], "full_code", None)
        return None

    def is_timeout_error(self, exc: Exception) -> bool:
        # DPY-4024 = call_timeout excedido (thin mode); ORA-03156 = idem em modo thick
        return self._full_code(exc) in _TIMEOUT_CODES

    def is_transient_error(self, exc: Exception) -> bool:
        if isinstance(exc, ConnectionError):
            return True
        # DPY-6005 ("cannot connect") não entra: engloba causas demais (host errado,
        # service inexistente, timeout) para repetir às cegas; sem instância Oracle, não validado.
        return self._full_code(exc) in _TRANSIENT_CODES

    def translate_params(self, sql: str, param_names: list[str]) -> str:
        """Traduz placeholders nomeados (:param) para Oracle (:pN, N = índice em param_names).

        Passo único: um nome já traduzido (ex.: parâmetro chamado ``p1``) não é
        reprocessado. Placeholder fora de ``param_names`` fica intacto. Parâmetro
        repetido reutiliza o mesmo ``:pN``.

        Exemplo:
            input:  "SELECT * FROM t WHERE x = :x AND (y = :y OR z = :y)", ["x", "y"]
            output: "SELECT * FROM t WHERE x = :p1 AND (y = :p2 OR z = :p2)"
        """
        index = {name: i for i, name in enumerate(param_names, 1)}

        def replace(match: re.Match) -> str:
            n = index.get(match.group(1))
            return match.group(0) if n is None else f":p{n}"

        return _PLACEHOLDER_RE.sub(replace, sql)
