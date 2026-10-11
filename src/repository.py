from dataclasses import dataclass
from typing import Iterable

import numpy as np
import psycopg

from src.chunking import Chunk
from src.db import DbError
from src.loaders import DocumentInfo


class DuplicateContent(Exception):
    """O índice único de documents (sha256 ou caminho) impediu a gravação."""


@dataclass(frozen=True)
class DocumentRow:
    id: int
    source_path: str
    sha256: str
    status: str
    pages: int
    source_id: int | None = None


@dataclass(frozen=True)
class SourceRow:
    id: int
    path: str
    recursive: bool
    last_indexed_at: object  # datetime | None


def folder_prefix(folder: str | None) -> str | None:
    """Prefixo de caminho que casa os arquivos dentro da pasta (F06, T7)."""
    return folder.rstrip("/") + "/" if folder else None


def count_indexed(conn: psycopg.Connection, folder: str | None = None) -> int:
    """Nº de documentos `indexed`, opcionalmente só os dentro de `folder`."""
    try:
        return conn.execute(
            "SELECT count(*) FROM documents WHERE status = 'indexed' "
            "AND (%(prefix)s::text IS NULL OR starts_with(source_path, %(prefix)s::text))",
            {"prefix": folder_prefix(folder)},
        ).fetchone()[0]
    except psycopg.errors.UndefinedTable:
        raise DbError("Tabela documents ausente. Execute init-db.") from None


_SELECT = "SELECT id, source_path, sha256, status, pages, source_id FROM documents"


def _fetch(conn: psycopg.Connection, where: str, value: str) -> DocumentRow | None:
    try:
        row = conn.execute(f"{_SELECT} WHERE {where} = %s", (value,)).fetchone()
    except psycopg.errors.UndefinedTable:
        raise DbError("Tabela documents ausente. Execute init-db.") from None
    return DocumentRow(*row) if row else None


def find_by_sha256(conn: psycopg.Connection, sha256: str) -> DocumentRow | None:
    return _fetch(conn, "sha256", sha256)


def find_by_path(conn: psycopg.Connection, path: str) -> DocumentRow | None:
    return _fetch(conn, "source_path", path)


def add_document(
    conn: psycopg.Connection,
    info: DocumentInfo,
    source_path: str,
    chunks: Iterable[tuple[Chunk, np.ndarray]],
    source_id: int | None = None,
) -> int:
    """Grava o documento e todos os trechos numa única transação. Devolve o id do documento.

    Levanta DuplicateContent se um índice único disparar (nada é gravado).
    """
    rows = list(chunks)
    try:
        with conn.transaction():
            document_id = conn.execute(
                "INSERT INTO documents (source_id, source_path, filename, file_type, sha256, pages, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'indexed') RETURNING id",
                (source_id, source_path, info.filename, info.file_type, info.sha256, info.page_count),
            ).fetchone()[0]
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (document_id, chunk_index, page, section, content, embedding) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [
                        (document_id, c.chunk_index, c.page, c.section, c.content, vector)
                        for c, vector in rows
                    ],
                )
    except psycopg.errors.UniqueViolation:
        raise DuplicateContent() from None
    except psycopg.errors.UndefinedTable:
        raise DbError("Tabela documents ou chunks ausente. Execute init-db.") from None
    return document_id


def _insert_chunks(conn: psycopg.Connection, document_id: int, rows: list[tuple[Chunk, np.ndarray]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO chunks (document_id, chunk_index, page, section, content, embedding) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [(document_id, c.chunk_index, c.page, c.section, c.content, vector) for c, vector in rows],
        )


def replace_document(
    conn: psycopg.Connection,
    document_id: int,
    info: DocumentInfo,
    chunks: Iterable[tuple[Chunk, np.ndarray]],
) -> None:
    """Troca os dados e os trechos de um documento numa única transação (F08, T1). Mantém o id.

    Levanta DuplicateContent se o novo `sha256` já pertence a outro documento (nada é alterado).
    """
    rows = list(chunks)
    try:
        with conn.transaction():
            conn.execute("SELECT id FROM documents WHERE id = %s FOR UPDATE", (document_id,))
            conn.execute(
                "UPDATE documents SET filename = %s, file_type = %s, sha256 = %s, pages = %s, "
                "status = 'indexed', error = NULL, updated_at = now() WHERE id = %s",
                (info.filename, info.file_type, info.sha256, info.page_count, document_id),
            )
            conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            _insert_chunks(conn, document_id, rows)
    except psycopg.errors.UniqueViolation:
        raise DuplicateContent() from None
    except psycopg.errors.UndefinedTable:
        raise DbError("Tabela documents ou chunks ausente. Execute init-db.") from None


def remove_document(conn: psycopg.Connection, document_id: int) -> None:
    """Remove o documento e, em cascata, seus trechos."""
    conn.execute("DELETE FROM documents WHERE id = %s", (document_id,))


def adopt_document(conn: psycopg.Connection, document_id: int, source_id: int) -> None:
    """Vincula um documento avulso a uma pasta, sem mexer nos trechos."""
    conn.execute("UPDATE documents SET source_id = %s WHERE id = %s", (source_id, document_id))


def list_documents_of_source(conn: psycopg.Connection, source_id: int) -> list[DocumentRow]:
    rows = conn.execute(f"{_SELECT} WHERE source_id = %s ORDER BY source_path", (source_id,)).fetchall()
    return [DocumentRow(*row) for row in rows]


_SOURCE_SELECT = "SELECT id, path, recursive, last_indexed_at FROM sources"


def _sources_error() -> DbError:
    return DbError("Tabela sources ausente. Execute init-db.")


def get_source(conn: psycopg.Connection, path: str) -> SourceRow | None:
    try:
        row = conn.execute(f"{_SOURCE_SELECT} WHERE path = %s", (path,)).fetchone()
    except psycopg.errors.UndefinedTable:
        raise _sources_error() from None
    return SourceRow(*row) if row else None


def list_sources(conn: psycopg.Connection) -> list[SourceRow]:
    try:
        rows = conn.execute(f"{_SOURCE_SELECT} ORDER BY id").fetchall()
    except psycopg.errors.UndefinedTable:
        raise _sources_error() from None
    return [SourceRow(*row) for row in rows]


def add_source(conn: psycopg.Connection, path: str, recursive: bool) -> SourceRow:
    try:
        row = conn.execute(
            "INSERT INTO sources (path, recursive) VALUES (%s, %s) "
            "ON CONFLICT (path) DO UPDATE SET path = EXCLUDED.path "
            "RETURNING id, path, recursive, last_indexed_at",
            (path, recursive),
        ).fetchone()
    except psycopg.errors.UndefinedTable:
        raise _sources_error() from None
    return SourceRow(*row)


def update_source(
    conn: psycopg.Connection,
    source_id: int,
    recursive: bool | None = None,
    indexed_now: bool = False,
) -> None:
    if recursive is not None:
        conn.execute("UPDATE sources SET recursive = %s WHERE id = %s", (recursive, source_id))
    if indexed_now:
        conn.execute("UPDATE sources SET last_indexed_at = now() WHERE id = %s", (source_id,))


def find_overlap(conn: psycopg.Connection, path: str) -> str | None:
    """Caminho de outra pasta registrada que contém `path` ou está dentro dele (F08, T7)."""
    prefix = path.rstrip("/") + "/"
    try:
        row = conn.execute(
            "SELECT path FROM sources WHERE path <> %(path)s "
            "AND (starts_with(%(prefix)s::text, rtrim(path, '/') || '/') OR starts_with(path, %(prefix)s::text)) "
            "ORDER BY id LIMIT 1",
            {"path": path, "prefix": prefix},
        ).fetchone()
    except psycopg.errors.UndefinedTable:
        raise _sources_error() from None
    return row[0] if row else None


_LOCK_KEY = "hashtextextended('rag-folder:' || %s, 0)"


def try_lock_folder(conn: psycopg.Connection, path: str) -> bool:
    """Lock consultivo por pasta, preso à conexão (F08, T5). False se outra execução o tem."""
    return conn.execute(f"SELECT pg_try_advisory_lock({_LOCK_KEY})", (path,)).fetchone()[0]


def unlock_folder(conn: psycopg.Connection, path: str) -> None:
    conn.execute(f"SELECT pg_advisory_unlock({_LOCK_KEY})", (path,))


@dataclass(frozen=True)
class DocumentListing:
    source_path: str
    file_type: str
    pages: int
    chunks: int
    status: str


@dataclass(frozen=True)
class SourceStats:
    path: str | None  # None = documentos avulsos
    recursive: bool | None
    documents: int
    chunks: int
    last_indexed_at: object  # datetime | None


def list_documents(conn: psycopg.Connection, folder: str | None = None) -> list[DocumentListing]:
    """Documentos com nº de trechos, por caminho; `folder` filtra por prefixo (F09, T7)."""
    try:
        rows = conn.execute(
            "SELECT d.source_path, d.file_type, d.pages, count(c.id), d.status "
            "FROM documents d LEFT JOIN chunks c ON c.document_id = d.id "
            "WHERE (%(prefix)s::text IS NULL OR starts_with(d.source_path, %(prefix)s::text)) "
            "GROUP BY d.id ORDER BY d.source_path",
            {"prefix": folder_prefix(folder)},
        ).fetchall()
    except psycopg.errors.UndefinedTable:
        raise DbError("Tabela documents ausente. Execute init-db.") from None
    return [DocumentListing(*row) for row in rows]


def source_stats(conn: psycopg.Connection) -> list[SourceStats]:
    """Pastas registradas (por cadastro) e, se houver, a linha dos documentos avulsos."""
    try:
        rows = conn.execute(
            "SELECT s.path, s.recursive, count(DISTINCT d.id), count(c.id), s.last_indexed_at "
            "FROM sources s LEFT JOIN documents d ON d.source_id = s.id "
            "LEFT JOIN chunks c ON c.document_id = d.id GROUP BY s.id ORDER BY s.id"
        ).fetchall()
        loose = conn.execute(
            "SELECT count(DISTINCT d.id), count(c.id) FROM documents d "
            "LEFT JOIN chunks c ON c.document_id = d.id WHERE d.source_id IS NULL"
        ).fetchone()
    except psycopg.errors.UndefinedTable:
        raise DbError("Tabela documents ausente. Execute init-db.") from None
    stats = [SourceStats(*row) for row in rows]
    if loose[0]:
        stats.append(SourceStats(None, None, loose[0], loose[1], None))
    return stats


def count_chunks(conn: psycopg.Connection, document_ids: list[int]) -> int:
    if not document_ids:
        return 0
    return conn.execute(
        "SELECT count(*) FROM chunks WHERE document_id = ANY(%s)", (document_ids,)
    ).fetchone()[0]


def remove_source(conn: psycopg.Connection, source_id: int) -> None:
    """Remove a pasta do registro; documentos e trechos saem em cascata."""
    conn.execute("DELETE FROM sources WHERE id = %s", (source_id,))
