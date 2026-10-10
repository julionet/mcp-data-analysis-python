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


_SELECT = "SELECT id, source_path, sha256, status, pages FROM documents"


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
) -> int:
    """Grava o documento e todos os trechos numa única transação. Devolve o id do documento.

    Levanta DuplicateContent se um índice único disparar (nada é gravado).
    """
    rows = list(chunks)
    try:
        with conn.transaction():
            document_id = conn.execute(
                "INSERT INTO documents (source_id, source_path, filename, file_type, sha256, pages, status) "
                "VALUES (NULL, %s, %s, %s, %s, %s, 'indexed') RETURNING id",
                (source_path, info.filename, info.file_type, info.sha256, info.page_count),
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
