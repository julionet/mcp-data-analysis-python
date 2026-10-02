from pathlib import Path
from urllib.parse import unquote, urlparse

import psycopg

from src import config

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

EXPECTED_TABLES = ["sources", "documents", "chunks", "app_meta"]
EXPECTED_INDEXES = ["documents_sha256_uniq", "chunks_embedding_hnsw", "chunks_tsv_gin"]
EMBEDDING_DIM = 1024

# variável -> o que dizer no aviso quando não estiver definida
OPTIONAL_ENV = {
    "ANTHROPIC_API_KEY": "necessária a partir da F07",
    "LLM_MODEL": "necessária a partir da F07",
    "EMBEDDING_MODEL": "necessária a partir da F04",
    "HF_TOKEN": "opcional",
}


class DbError(Exception):
    """Erro esperado, com mensagem já pronta para a pessoa (sem a senha)."""


def _parse(url: str) -> tuple[str, int, str, str]:
    """(host, porta, banco, usuário) da URL, sem a senha."""
    parts = urlparse(url)
    return (
        parts.hostname or "localhost",
        parts.port or 5432,
        unquote(parts.path.lstrip("/")),
        unquote(parts.username or ""),
    )


def describe_url(url: str) -> str:
    """'host:porta/banco (usuário x)', sem a senha."""
    host, port, database, user = _parse(url)
    return f"{host}:{port}/{database} (usuário {user})"


def connect() -> psycopg.Connection:
    url = config.DATABASE_URL
    if not url:
        raise DbError("DATABASE_URL não definida. Copie .env.example para .env e preencha.")

    host, port, database, user = _parse(url)

    try:
        return psycopg.connect(url, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as e:
        text = str(e).lower()
        sqlstate = getattr(e, "sqlstate", None)
        if sqlstate == "28P01" or "password authentication failed" in text or "authentication failed" in text:
            raise DbError(f'Falha de autenticação para o usuário "{user}".') from None
        if sqlstate == "3D000" or ("database" in text and "does not exist" in text):
            raise DbError(f'Banco "{database}" não existe. Execute sql/setup_admin.sql.') from None
        if "role" in text and "does not exist" in text:
            raise DbError(f'Falha de autenticação para o usuário "{user}".') from None
        if "connection refused" in text or "timeout" in text or "could not connect" in text:
            raise DbError(
                f"Não foi possível conectar ao Postgres em {host}:{port}. Ele está em execução?"
            ) from None
        raise DbError(f"Não foi possível conectar ao Postgres em {host}:{port}.") from None


def _extension_version(conn: psycopg.Connection) -> str | None:
    row = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    return row[0] if row else None


def _existing(conn: psycopg.Connection, kind: str) -> set[str]:
    if kind == "tables":
        query = "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    else:
        query = "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
    return {r[0] for r in conn.execute(query).fetchall()}


def init_db() -> list[str]:
    """Aplica sql/001_init.sql. Devolve as linhas de saída para a CLI."""
    conn = connect()
    with conn:
        lines = [f"Conectado: {describe_url(config.DATABASE_URL)}"]

        version = _extension_version(conn)
        if version is None:
            database = conn.info.dbname
            raise DbError(
                f'Extensão "vector" não instalada em "{database}". '
                "Execute sql/setup_admin.sql como superusuário."
            )
        lines.append(f"Extensão vector {version}: OK")

        tables_before = _existing(conn, "tables")
        indexes_before = _existing(conn, "indexes")

        sql = (SQL_DIR / "001_init.sql").read_text(encoding="utf-8")
        try:
            with conn.transaction():
                conn.execute(sql)
        except psycopg.Error as e:
            raise DbError(f"Erro ao aplicar o esquema (nada foi alterado): {e}") from None

        new_tables = [t for t in EXPECTED_TABLES if t in _existing(conn, "tables") - tables_before]
        new_indexes = [i for i in EXPECTED_INDEXES if i in _existing(conn, "indexes") - indexes_before]

        if new_tables:
            lines.append(f"Tabelas criadas: {', '.join(new_tables)}")
        if new_indexes:
            lines.append(f"Índices criados: {', '.join(new_indexes)}")
        if new_tables or new_indexes:
            lines.append("Esquema aplicado com sucesso.")
        else:
            lines.append("Esquema já estava atualizado.")
    return lines


def check_environment() -> tuple[list[str], int]:
    """Roda as verificações. Devolve (linhas, nº de falhas)."""
    lines: list[str] = []
    failures = 0
    warnings = 0

    def ok(msg: str) -> None:
        lines.append(f"[OK]    {msg}")

    def fail(msg: str) -> None:
        nonlocal failures
        failures += 1
        lines.append(f"[FALHA] {msg}")

    def warn(msg: str) -> None:
        nonlocal warnings
        warnings += 1
        lines.append(f"[AVISO] {msg}")

    url = config.DATABASE_URL
    if not url:
        fail("DATABASE_URL não definida. Copie .env.example para .env e preencha.")
    else:
        ok(f"DATABASE_URL definida: {describe_url(url)}")
        try:
            conn = connect()
        except DbError as e:
            fail(str(e))
        else:
            with conn:
                version = conn.execute("SHOW server_version").fetchone()[0].split()[0]
                ok(f"Conexão com o Postgres {version}")

                ext = _extension_version(conn)
                if ext:
                    ok(f"Extensão vector {ext}")
                else:
                    fail('Extensão "vector" ausente. Execute sql/setup_admin.sql como superusuário.')

                tables = _existing(conn, "tables")
                missing_tables = [t for t in EXPECTED_TABLES if t not in tables]
                for t in missing_tables:
                    fail(f"Tabela {t} ausente. Execute init-db.")
                if not missing_tables:
                    ok(f"Tabelas: {', '.join(EXPECTED_TABLES)}")

                indexes = _existing(conn, "indexes")
                missing_indexes = [i for i in EXPECTED_INDEXES if i not in indexes]
                for i in missing_indexes:
                    fail(f"Índice {i} ausente. Execute init-db.")
                if not missing_indexes:
                    ok(f"Índices: {', '.join(EXPECTED_INDEXES)}")

                if "chunks" in tables:
                    row = conn.execute(
                        "SELECT atttypmod FROM pg_attribute "
                        "WHERE attrelid = 'public.chunks'::regclass AND attname = 'embedding'"
                    ).fetchone()
                    dim = row[0] if row else None
                    if dim == EMBEDDING_DIM:
                        ok(f"chunks.embedding com {EMBEDDING_DIM} dimensões")
                    else:
                        fail(f"chunks.embedding com {dim} dimensões (esperado {EMBEDDING_DIM}).")

    for name, note in OPTIONAL_ENV.items():
        if not getattr(config, name):
            warn(f"{name} não definida ({note}).")

    status = "ambiente OK" if failures == 0 else "ambiente com problemas"
    lines.append(f"Resultado: {status} ({failures} falhas, {warnings} avisos)")
    return lines, failures
