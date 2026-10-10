import time
from dataclasses import dataclass
from pathlib import Path

from src import config, db, repository
from src.embeddings import Embedder, EmbeddingError
from src.retrieval import FETCH_K, TOP_K, SearchHit, search


class SearchError(Exception):
    """Erro esperado, com mensagem já pronta para a pessoa."""


@dataclass(frozen=True)
class SearchOutcome:
    status: str  # "ok" | "empty_base" | "no_documents_in_folder"
    method: str
    top_k: int
    fetch_k: int
    folder: str | None
    hits: list[SearchHit]
    elapsed: float = 0.0


def run_search(
    text: str,
    method: str = "rrf",
    top_k: int = TOP_K,
    fetch_k: int = FETCH_K,
    folder: str | None = None,
) -> SearchOutcome:
    """Fluxo da seção 4.1 da F06: base vazia, conferência do modelo, vetor da pergunta, busca."""
    text = text.strip()
    if not text:
        raise SearchError("Informe a pergunta.")
    folder = str(Path(folder).resolve()) if folder else None
    fetch_k = max(fetch_k, top_k)
    started = time.perf_counter()

    def outcome(status: str, hits: list[SearchHit] | None = None) -> SearchOutcome:
        return SearchOutcome(status, method, top_k, fetch_k, folder, hits or [], time.perf_counter() - started)

    conn = db.connect()
    try:
        if repository.count_indexed(conn) == 0:
            return outcome("empty_base")
        if folder and repository.count_indexed(conn, folder) == 0:
            return outcome("no_documents_in_folder")

        vector = None
        if method != "lexical":
            model_name = config.EMBEDDING_MODEL
            if not model_name:
                raise EmbeddingError("EMBEDDING_MODEL não definida. Copie .env.example para .env e preencha.")
            db.ensure_embedding_model(conn, model_name)  # falha antes de carregar o modelo (T1)
            embedder = Embedder(model_name)
            embedder.check_dimension(db.EMBEDDING_DIM)
            vector = embedder.embed_one(text)

        hits = search(conn, text, vector, method, top_k, fetch_k, folder)
        return outcome("ok", hits)
    finally:
        conn.close()
