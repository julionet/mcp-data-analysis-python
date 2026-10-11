from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from src import db, repository
from src.folder_ingestion import ConfirmUnavailable
from src.repository import DocumentListing, SourceStats


class ManagementError(Exception):
    """Erro esperado, com mensagem já pronta para a pessoa."""


@dataclass(frozen=True)
class DeleteResult:
    status: str  # removed | declined
    kind: str  # document | folder
    target: str
    documents: int = 0
    chunks: int = 0
    paths: list[str] = field(default_factory=list)


# confirm(kind, target, paths, chunks) -> bool; levanta ConfirmUnavailable sem terminal
Confirm = Callable[[str, str, list[str], int], bool]


def list_folders() -> list[SourceStats]:
    conn = db.connect()
    try:
        return repository.source_stats(conn)
    finally:
        conn.close()


def list_documents(folder: str | None = None) -> list[DocumentListing]:
    folder = str(Path(folder).resolve()) if folder else None
    conn = db.connect()
    try:
        return repository.list_documents(conn, folder)
    finally:
        conn.close()


def delete_target(target: str, confirm: Confirm) -> DeleteResult:
    """Fluxo da seção 4.1 da F09: resolve (T1), trava (T5), confirma (T4) e remove numa transação."""
    path = str(Path(target).resolve())
    conn = db.connect()
    locked: str | None = None
    try:
        document = repository.find_by_path(conn, path)
        source = None if document else repository.get_source(conn, path)
        if document is None and source is None:
            others = [s for s in repository.list_sources(conn) if path.startswith(s.path.rstrip("/") + "/")]
            if others:
                raise ManagementError(
                    f"{path} não é uma pasta registrada. Para remover um arquivo, informe o arquivo; "
                    f"para a pasta, informe a pasta registrada ({others[0].path})."
                )
            raise ManagementError(f"{path} não está na base. Veja os documentos com: python -m src.cli list")

        lock_path = source.path if source else None
        if document and document.source_id is not None:
            owner = next((s for s in repository.list_sources(conn) if s.id == document.source_id), None)
            lock_path = owner.path if owner else None
        if lock_path:
            if not repository.try_lock_folder(conn, lock_path):
                raise ManagementError(
                    f"Já existe uma atualização da pasta {lock_path} em andamento. "
                    "Tente novamente quando ela terminar."
                )
            locked = lock_path

        if source:
            docs = repository.list_documents_of_source(conn, source.id)
            kind = "folder"
        else:
            docs = [document]
            kind = "document"
        ids = [d.id for d in docs]
        paths = [d.source_path for d in docs]
        chunks = repository.count_chunks(conn, ids)

        if not confirm(kind, path, paths, chunks):
            return DeleteResult("declined", kind, path, len(docs), chunks, paths)

        with conn.transaction():
            if source:
                repository.remove_source(conn, source.id)
            else:
                repository.remove_document(conn, document.id)
        return DeleteResult("removed", kind, path, len(docs), chunks, paths)
    finally:
        if locked:
            try:
                repository.unlock_folder(conn, locked)
            except Exception:
                pass
        conn.close()


__all__ = ["ConfirmUnavailable", "DeleteResult", "ManagementError", "delete_target", "list_documents", "list_folders"]
