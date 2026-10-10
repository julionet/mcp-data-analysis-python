import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from src import config, db, repository
from src.embeddings import EmbeddingError
from src.ingestion import IngestError, ModelProvider, Progress, process_file
from src.loaders import ACCEPTED_TYPES, LoaderError


class FolderError(Exception):
    """Erro esperado de uma pasta, com mensagem já pronta para a pessoa."""


class ConfirmUnavailable(Exception):
    """A confirmação do --prune não pode ser pedida (entrada que não é um terminal)."""


@dataclass(frozen=True)
class FileResult:
    path: str  # relativo à pasta
    outcome: str  # created|updated|unchanged|adopted|duplicate|failed|absent|removed|ignored
    chunk_count: int = 0
    detail: str = ""


@dataclass
class FolderResult:
    folder: str
    registered_now: bool = False
    recursive: bool = True
    files: list[FileResult] = field(default_factory=list)  # aceitos, em ordem, e depois os ausentes
    ignored: list[FileResult] = field(default_factory=list)
    out_of_scope: int = 0  # documentos em subpastas de uma pasta não recursiva (T13)
    prune_status: str | None = None  # none | removed | declined | unavailable | cancelled
    interrupted: bool = False
    error: str | None = None  # erro da pasta (trava, não encontrada, não registrada)
    fatal: str | None = None  # erro global no meio da execução (modelo, banco)
    elapsed: float = 0.0

    def count(self, outcome: str) -> int:
        return sum(1 for f in self.files if f.outcome == outcome)

    @property
    def accepted(self) -> int:
        return sum(1 for f in self.files if f.outcome not in ("absent", "removed"))

    @property
    def has_problem(self) -> bool:
        """Código de saída 1 (4.3 da F08)."""
        return bool(
            self.error
            or self.fatal
            or self.interrupted
            or self.count("failed")
            or self.prune_status in ("unavailable", "cancelled")
        )


@dataclass(frozen=True)
class Scan:
    files: list[Path]
    ignored: list[FileResult]


class Reporter:
    """Ganchos de andamento; a CLI sobrescreve o que quiser mostrar."""

    def file_start(self, index: int, total: int, rel: str) -> Progress | None:
        return None

    def file_end(self) -> None:
        pass

    def before_prune(self, result: FolderResult) -> None:
        pass


# confirm(pasta, caminhos ausentes, pasta_nao_encontrada) -> True para remover
Confirm = Callable[[str, list[str], bool], bool]


def _rel(folder: Path, path: Path) -> str:
    return path.relative_to(folder).as_posix()


def scan_folder(folder: Path, recursive: bool) -> Scan:
    """Arquivos aceitos (em ordem de caminho) e ignorados, com o motivo (T6)."""
    files: list[Path] = []
    ignored: list[FileResult] = []

    def walk(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            ignored.append(FileResult(_rel(folder, directory) + "/", "ignored", detail="sem permissão de leitura"))
            return
        for entry in entries:
            path = Path(entry.path)
            rel = _rel(folder, path)
            if entry.is_symlink():
                ignored.append(FileResult(rel, "ignored", detail="link simbólico"))
            elif entry.name.startswith("."):
                ignored.append(FileResult(rel + ("/" if entry.is_dir() else ""), "ignored", detail="oculto"))
            elif entry.is_dir():
                if recursive:
                    walk(path)
            elif entry.is_file():
                if path.suffix.lower() in ACCEPTED_TYPES:
                    files.append(path)
                else:
                    ignored.append(FileResult(rel, "ignored", detail="formato não aceito"))

    walk(folder)
    files.sort(key=lambda p: _rel(folder, p))
    ignored.sort(key=lambda f: f.path)
    return Scan(files, ignored)


def _file_result(rel: str, result) -> FileResult:
    if result.outcome == "duplicate":
        note = " (versão anterior removida)" if result.replaced_previous else ""
        return FileResult(rel, "duplicate", detail=f"duplicado de {result.duplicate_of}{note}")
    return FileResult(rel, result.outcome, chunk_count=result.chunk_count)


def _run_folder(
    conn,
    folder: Path,
    source: repository.SourceRow,
    provider: ModelProvider,
    force: bool,
    prune: bool,
    reporter: Reporter,
    confirm: Confirm | None,
    registered_now: bool,
) -> FolderResult:
    """Fluxo 4.1 da F08, com a pasta já registrada e a trava tomada."""
    started = time.perf_counter()
    result = FolderResult(str(folder), registered_now, source.recursive)
    folder_missing = not folder.is_dir()
    if folder_missing and not prune:
        result.error = f"A pasta {folder} não foi encontrada em disco. Nada foi alterado."
        return result

    try:
        if not folder_missing:
            scan = scan_folder(folder, source.recursive)
            result.ignored = scan.ignored
            total = len(scan.files)
            for index, path in enumerate(scan.files, 1):
                rel = _rel(folder, path)
                progress = reporter.file_start(index, total, rel)
                try:
                    outcome = process_file(conn, path, source.id, provider, force, progress)
                    result.files.append(_file_result(rel, outcome))
                except (LoaderError, IngestError) as e:
                    detail = str(e)
                    if repository.find_by_path(conn, str(path)) is not None:
                        detail += " (mantida a versão anterior)"
                    result.files.append(FileResult(rel, "failed", detail=detail))
                finally:
                    reporter.file_end()

        documents = repository.list_documents_of_source(conn, source.id)
        absent = [d for d in documents if folder_missing or not os.path.exists(d.source_path)]
        absent_ids = {d.id for d in absent}
        for d in absent:
            rel = os.path.relpath(d.source_path, folder)
            result.files.append(FileResult(rel, "absent", detail="não existe mais em disco"))
        if not source.recursive and not folder_missing:
            result.out_of_scope = sum(
                1 for d in documents if d.id not in absent_ids and Path(d.source_path).parent != folder
            )

        if prune:
            reporter.before_prune(result)
            if not absent:
                result.prune_status = "none"
            else:
                _prune(conn, result, absent, confirm, folder_missing)

        repository.update_source(conn, source.id, indexed_now=True)  # T11
    except KeyboardInterrupt:
        result.interrupted = True
    except (EmbeddingError, db.DbError, psycopg.Error) as e:
        result.fatal = str(e)
    result.elapsed = time.perf_counter() - started
    return result


def _prune(conn, result: FolderResult, absent, confirm: Confirm | None, folder_missing: bool) -> None:
    paths = [d.source_path for d in absent]
    try:
        if confirm is None:
            raise ConfirmUnavailable()
        confirmed = confirm(result.folder, paths, folder_missing)
    except ConfirmUnavailable:
        result.prune_status = "unavailable"
        return
    except KeyboardInterrupt:
        result.prune_status = "cancelled"
        return
    if not confirmed:
        result.prune_status = "declined"
        return
    for d in absent:
        repository.remove_document(conn, d.id)
    result.files = [
        FileResult(f.path, "removed", detail="removido da base") if f.outcome == "absent" else f
        for f in result.files
    ]
    result.prune_status = "removed"


def _locked(conn, folder: Path) -> None:
    if not repository.try_lock_folder(conn, str(folder)):
        raise FolderError(
            f"Já existe uma atualização da pasta {folder} em andamento. Tente novamente quando ela terminar."
        )


def ingest_folder(
    path: str | Path,
    recursive: bool | None = None,
    force: bool = False,
    prune: bool = False,
    reporter: Reporter | None = None,
    confirm: Confirm | None = None,
) -> FolderResult:
    """Cadastra ou atualiza uma pasta (F08, 4.1). Erros da pasta levantam FolderError."""
    reporter = reporter or Reporter()
    folder = Path(path).resolve()
    if not folder.is_dir():
        raise LoaderError(f"Arquivo não encontrado: {folder}")

    conn = db.connect()
    try:
        overlap = repository.find_overlap(conn, str(folder))
        if overlap:
            raise FolderError(f"{folder} se sobrepõe à pasta já registrada {overlap}. Use uma delas.")
        _locked(conn, folder)
        try:
            source = repository.get_source(conn, str(folder))
            registered_now = source is None
            if source is None:
                source = repository.add_source(conn, str(folder), True if recursive is None else recursive)
            elif recursive is not None and recursive != source.recursive:
                repository.update_source(conn, source.id, recursive=recursive)
                source = repository.SourceRow(source.id, source.path, recursive, source.last_indexed_at)
            provider = ModelProvider(conn, config.EMBEDDING_MODEL)
            return _run_folder(conn, folder, source, provider, force, prune, reporter, confirm, registered_now)
        finally:
            repository.unlock_folder(conn, str(folder))
    finally:
        conn.close()


def reindex_folders(
    path: str | Path | None = None,
    prune: bool = False,
    reporter: Reporter | None = None,
    confirm: Confirm | None = None,
) -> Iterator[FolderResult]:
    """Reprocessa a pasta registrada `path`, ou todas se for None (F08). Uma por vez, em ordem de cadastro."""
    reporter = reporter or Reporter()
    conn = db.connect()
    try:
        if path is not None:
            folder = Path(path).resolve()
            source = repository.get_source(conn, str(folder))
            if source is None:
                yield FolderResult(
                    str(folder),
                    error=f"{folder} não está registrada. Cadastre com: python -m src.cli ingest {folder}",
                )
                return
            sources = [source]
        else:
            sources = repository.list_sources(conn)
        provider = ModelProvider(conn, config.EMBEDDING_MODEL)
        for source in sources:
            folder = Path(source.path)
            try:
                _locked(conn, folder)
            except FolderError as e:
                yield FolderResult(str(folder), recursive=source.recursive, error=str(e))
                continue
            try:
                result = _run_folder(conn, folder, source, provider, False, prune, reporter, confirm, False)
            finally:
                repository.unlock_folder(conn, str(folder))
            yield result
            if result.fatal or result.interrupted:
                return
    finally:
        conn.close()
