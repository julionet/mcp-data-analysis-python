from pathlib import Path
from urllib.parse import unquote, urlparse

import psycopg

from src import config

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

EXPECTED_TABLES = ["sources", "documents", "chunks", "app_meta"]
EXPECTED_INDEXES = ["documents_sha256_uniq", "chunks_embedding_hnsw", "chunks_tsv_gin", "chunks_tsv_en_gin"]
EMBEDDING_DIM = 1024

# variável -> o que dizer no aviso quando não estiver definida
OPTIONAL_ENV = {
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


def _register_vector(conn: psycopg.Connection) -> None:
    """Adaptador do tipo vector. Sem a extensão (init-db e check ainda reportam isso), segue sem ele."""
    from pgvector.psycopg import register_vector

    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        pass


def connect() -> psycopg.Connection:
    url = config.DATABASE_URL
    if not url:
        raise DbError("DATABASE_URL não definida. Copie .env.example para .env e preencha.")

    host, port, database, user = _parse(url)

    try:
        conn = psycopg.connect(url, autocommit=True, connect_timeout=5)
        _register_vector(conn)
        return conn
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


def _migrations() -> list[Path]:
    """Migrações sql/NNN_*.sql em ordem de nome."""
    return sorted(SQL_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def _file_type_constraint(conn: psycopg.Connection) -> str | None:
    """Definição do CHECK de documents.file_type, ou None se a tabela/restrição não existe."""
    row = conn.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname = 'documents_file_type_check' AND conrelid = to_regclass('public.documents')"
    ).fetchone()
    return row[0] if row else None


def _allows_md(definition: str | None) -> bool:
    return definition is not None and "'md'" in definition


def mismatch_message(configured: str, registered: str) -> str:
    return (
        f'O modelo de embeddings configurado ("{configured}") é diferente do registrado no banco '
        f'("{registered}"). Os vetores existentes não são comparáveis. '
        "Reindexe a base ou restaure EMBEDDING_MODEL no .env."
    )


def get_embedding_meta(conn: psycopg.Connection) -> tuple[str, int] | None:
    """(modelo, dimensão) registrados em app_meta, ou None se ainda não há registro."""
    try:
        rows = dict(
            conn.execute(
                "SELECT key, value FROM app_meta WHERE key IN ('embedding_model', 'embedding_dim')"
            ).fetchall()
        )
    except psycopg.errors.UndefinedTable:
        raise DbError("Tabela app_meta ausente. Execute init-db.") from None
    if "embedding_model" not in rows:
        return None
    try:
        dim = int(rows.get("embedding_dim", 0))
    except ValueError:
        dim = 0
    return rows["embedding_model"], dim


def ensure_embedding_model(conn: psycopg.Connection, model_name: str) -> bool:
    """True se o modelo já está registrado e confere; False se ainda não há registro.

    Levanta DbError se o modelo registrado for outro (T6 da F04).
    """
    meta = get_embedding_meta(conn)
    if meta is None:
        return False
    if meta[0] != model_name:
        raise DbError(mismatch_message(model_name, meta[0]))
    return True


def register_embedding_model(conn: psycopg.Connection, model_name: str, dim: int) -> bool:
    """Grava o modelo em app_meta só se ainda não existir (nunca sobrescreve). True se gravou."""
    with conn.transaction():
        cur = conn.execute(
            "INSERT INTO app_meta (key, value) VALUES ('embedding_model', %s) ON CONFLICT DO NOTHING",
            (model_name,),
        )
        inserted = cur.rowcount == 1
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES ('embedding_dim', %s) ON CONFLICT DO NOTHING",
            (str(dim),),
        )
    return inserted


def init_db() -> list[str]:
    """Aplica as migrações sql/NNN_*.sql em ordem. Devolve as linhas de saída para a CLI."""
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

        constraint_before = _file_type_constraint(conn)
        try:
            with conn.transaction():
                for migration in _migrations():
                    conn.execute(migration.read_text(encoding="utf-8"))
        except psycopg.Error as e:
            raise DbError(f"Erro ao aplicar o esquema (nada foi alterado): {e}") from None

        new_tables = [t for t in EXPECTED_TABLES if t in _existing(conn, "tables") - tables_before]
        new_indexes = [i for i in EXPECTED_INDEXES if i in _existing(conn, "indexes") - indexes_before]

        if new_tables:
            lines.append(f"Tabelas criadas: {', '.join(new_tables)}")
        if new_indexes:
            lines.append(f"Índices criados: {', '.join(new_indexes)}")
        constraint_changed = not _allows_md(constraint_before) and _allows_md(_file_type_constraint(conn))
        if constraint_changed and "documents" not in new_tables:
            lines.append("Restrição documents.file_type atualizada (txt, md, pdf).")
        if new_tables or new_indexes or constraint_changed:
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

                if "chunks" in tables:
                    columns = {
                        row[0]
                        for row in conn.execute(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = 'public' AND table_name = 'chunks'"
                        ).fetchall()
                    }
                    if "tsv_en" not in columns:
                        fail("Busca textual desatualizada (chunks.tsv_en ausente). Execute init-db.")
                    else:
                        ok("Busca textual em português e inglês (chunks.tsv e chunks.tsv_en)")

                if "documents" in tables and not _allows_md(_file_type_constraint(conn)):
                    fail('Restrição documents.file_type não aceita "md". Execute init-db.')

                if "app_meta" in tables:
                    meta = get_embedding_meta(conn)
                    if meta is None:
                        warn("Modelo de embeddings ainda não registrado (será gravado na primeira vetorização).")
                    else:
                        registered, registered_dim = meta
                        if config.EMBEDDING_MODEL and registered != config.EMBEDDING_MODEL:
                            fail(mismatch_message(config.EMBEDDING_MODEL, registered))
                        elif registered_dim != EMBEDDING_DIM:
                            fail(
                                f'Modelo de embeddings registrado ("{registered}") com {registered_dim} '
                                f"dimensões (esperado {EMBEDDING_DIM})."
                            )
                        else:
                            ok(f"Modelo de embeddings: {registered} ({registered_dim} dimensões)")

    for name in ("ANTHROPIC_API_KEY", "LLM_MODEL"):  # exigidas pelo ask (F07); só a presença é conferida
        if getattr(config, name):
            ok(f"{name} definida")
        else:
            fail(f"{name} não definida. Copie .env.example para .env e preencha.")

    for name, note in OPTIONAL_ENV.items():
        if not getattr(config, name):
            warn(f"{name} não definida ({note}).")

    status = "ambiente OK" if failures == 0 else "ambiente com problemas"
    lines.append(f"Resultado: {status} ({failures} falhas, {warnings} avisos)")
    return lines, failures
