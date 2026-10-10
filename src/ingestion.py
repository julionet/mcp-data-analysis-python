import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import psycopg

from src import config, db, repository
from src.chunking import chunk_pages
from src.embeddings import Embedder, EmbeddingError, embed_chunks
from src.loaders import DocumentInfo, inspect_document, iter_pages

# progress(página atual, total de páginas, trechos prontos, trechos/s)
Progress = Callable[[int, int, int, float], None]


class IngestError(Exception):
    """Erro esperado, com mensagem já pronta para a pessoa."""


@dataclass(frozen=True)
class IngestResult:
    outcome: str  # "created" | "updated" | "unchanged" | "adopted" | "duplicate"
    path: Path
    info: DocumentInfo
    document_id: int | None = None
    chunk_count: int = 0
    duplicate_of: str | None = None
    replaced_previous: bool = False  # duplicado de um arquivo que já estava cadastrado: a versão anterior saiu (F08)
    elapsed: float = 0.0
    model_name: str | None = None
    model_registered: bool = False  # True se esta execução gravou o modelo em app_meta


class ModelProvider:
    """Confere o modelo (F04) e carrega o Embedder só na primeira vez que alguém precisa dele (F08, T4)."""

    def __init__(self, conn, model_name: str | None) -> None:
        self.conn = conn
        self.model_name = model_name
        self._embedder: Embedder | None = None
        self._registered = False

    def embedder(self) -> Embedder:
        if self._embedder is None:
            if not self.model_name:
                raise EmbeddingError("EMBEDDING_MODEL não definida. Copie .env.example para .env e preencha.")
            self._registered = db.ensure_embedding_model(self.conn, self.model_name)  # falha antes de carregar
            embedder = Embedder(self.model_name)
            embedder.check_dimension(db.EMBEDDING_DIM)
            self._embedder = embedder
        return self._embedder

    def after_write(self) -> bool:
        """Registra o modelo em app_meta após a primeira gravação. True se esta chamada gravou."""
        if self._registered:
            return False
        self._registered = True
        return db.register_embedding_model(self.conn, self.model_name, self._embedder.dimension)


def _classify(conn, path: Path, info: DocumentInfo, source_id: int | None, force: bool):
    """(ação, documento no caminho, documento com o mesmo hash). Tabela T1 da F08."""
    by_sha = repository.find_by_sha256(conn, info.sha256)
    by_path = repository.find_by_path(conn, str(path))
    if by_sha is not None:
        if by_sha.source_path == str(path):
            if force:
                return "updated", by_sha, by_sha
            if source_id is not None and by_sha.source_id is None:
                return "adopted", by_sha, by_sha
            return "unchanged", by_sha, by_sha
        return "duplicate", by_path, by_sha
    if by_path is not None:
        return "updated", by_path, None
    return "created", None, None


def process_file(
    conn,
    path: Path,
    source_id: int | None,
    provider: ModelProvider,
    force: bool = False,
    progress: Progress | None = None,
    info: DocumentInfo | None = None,
) -> IngestResult:
    """Cadastra, atualiza ou classifica um arquivo (F05, 4.1, e F08, T1). Nada é gravado se algo falhar."""
    info = info or inspect_document(path)
    pairs = None
    started = time.perf_counter()

    for _ in range(2):
        action, by_path, by_sha = _classify(conn, path, info, source_id, force)

        if action == "unchanged":
            return IngestResult("unchanged", path, info, document_id=by_sha.id)
        if action == "adopted":
            repository.adopt_document(conn, by_sha.id, source_id)
            return IngestResult("adopted", path, info, document_id=by_sha.id)
        if action == "duplicate":
            if by_path is not None:  # o arquivo mudou e ficou igual a outro: a versão anterior sai (R5)
                repository.remove_document(conn, by_path.id)
            return IngestResult(
                "duplicate",
                path,
                info,
                document_id=by_sha.id,
                duplicate_of=by_sha.source_path,
                replaced_previous=by_path is not None,
            )

        if pairs is None:
            embedder = provider.embedder()
            started = time.perf_counter()
            pairs = []
            for chunk, vector in embed_chunks(embedder, chunk_pages(iter_pages(path), "structured")):
                pairs.append((chunk, vector))
                if progress:
                    elapsed = time.perf_counter() - started
                    progress(chunk.page, info.page_count, len(pairs), len(pairs) / elapsed if elapsed else 0.0)
            if not pairs:
                raise IngestError(f"Nenhum trecho gerado a partir de {path.name}.")

        try:
            if action == "updated":
                document_id = by_path.id
                repository.replace_document(conn, document_id, info, pairs)
            else:
                document_id = repository.add_document(conn, info, str(path), pairs, source_id)
        except repository.DuplicateContent:
            continue  # outra execução cadastrou o mesmo conteúdo ao mesmo tempo (T3 da F05): reclassifica
        except psycopg.Error as e:
            reason = (str(e).strip().splitlines() or [type(e).__name__])[0]
            raise IngestError(f"Erro ao gravar o documento (nada foi gravado): {reason}") from None

        return IngestResult(
            action,
            path,
            info,
            document_id=document_id,
            chunk_count=len(pairs),
            elapsed=time.perf_counter() - started,
            model_name=provider.model_name,
            model_registered=provider.after_write(),
        )

    raise IngestError("Erro ao gravar o documento (nada foi gravado): conflito de cadastro.")


def ingest_file(path: str | Path, progress: Progress | None = None, force: bool = False) -> IngestResult:
    """Cadastra um arquivo avulso TXT, MD ou PDF; arquivo alterado no mesmo caminho é substituído (F08)."""
    path = Path(path).resolve()
    if path.is_dir():
        raise IngestError(f"{path} é uma pasta; use o cadastro de pastas.")
    model_name = config.EMBEDDING_MODEL
    if not model_name:
        raise EmbeddingError("EMBEDDING_MODEL não definida. Copie .env.example para .env e preencha.")

    info = inspect_document(path)  # falha cedo, antes de conectar, com a mensagem da F02
    conn = db.connect()
    try:
        return process_file(conn, path, None, ModelProvider(conn, model_name), force, progress, info)
    finally:
        conn.close()
