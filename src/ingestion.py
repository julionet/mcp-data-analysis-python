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
    outcome: str  # "created" | "unchanged" | "duplicate"
    path: Path
    info: DocumentInfo
    document_id: int | None = None
    chunk_count: int = 0
    duplicate_of: str | None = None
    elapsed: float = 0.0
    model_name: str | None = None
    model_registered: bool = False  # True se esta execução gravou o modelo em app_meta


def _existing_result(conn, path: Path, info: DocumentInfo) -> IngestResult | None:
    """Duplicado, já cadastrado ou alterado (este último é erro). None se o arquivo é novo."""
    by_sha = repository.find_by_sha256(conn, info.sha256)
    if by_sha is not None:
        if by_sha.source_path == str(path):
            return IngestResult("unchanged", path, info, document_id=by_sha.id)
        return IngestResult("duplicate", path, info, document_id=by_sha.id, duplicate_of=by_sha.source_path)
    if repository.find_by_path(conn, str(path)) is not None:
        raise IngestError(
            f"O arquivo {path} mudou desde o cadastro. "
            "A atualização de arquivos alterados ainda não existe."
        )
    return None


def ingest_file(path: str | Path, progress: Progress | None = None) -> IngestResult:
    """Cadastra um TXT, MD ou PDF (F05, seção 4.1). Nada é gravado se algo falhar."""
    path = Path(path).resolve()
    if path.is_dir():
        raise IngestError(
            f"{path} é uma pasta. O cadastro de pastas será oferecido na F08; informe um arquivo."
        )
    model_name = config.EMBEDDING_MODEL
    if not model_name:
        raise EmbeddingError("EMBEDDING_MODEL não definida. Copie .env.example para .env e preencha.")

    info = inspect_document(path)

    conn = db.connect()
    try:
        existing = _existing_result(conn, path, info)
        if existing is not None:
            return existing

        registered = db.ensure_embedding_model(conn, model_name)  # falha antes de carregar o modelo
        embedder = Embedder(model_name)
        embedder.check_dimension(db.EMBEDDING_DIM)

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
            document_id = repository.add_document(conn, info, str(path), pairs)
        except repository.DuplicateContent:
            # outra execução cadastrou o mesmo conteúdo ao mesmo tempo (T3)
            existing = _existing_result(conn, path, info)
            if existing is None:
                raise IngestError("Erro ao gravar o documento (nada foi gravado): conflito de cadastro.") from None
            return existing
        except psycopg.Error as e:
            reason = (str(e).strip().splitlines() or [type(e).__name__])[0]
            raise IngestError(f"Erro ao gravar o documento (nada foi gravado): {reason}") from None

        model_registered = False
        if not registered:
            model_registered = db.register_embedding_model(conn, model_name, embedder.dimension)

        return IngestResult(
            "created",
            path,
            info,
            document_id=document_id,
            chunk_count=len(pairs),
            elapsed=time.perf_counter() - started,
            model_name=model_name,
            model_registered=model_registered,
        )
    finally:
        conn.close()

