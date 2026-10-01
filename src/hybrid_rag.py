from pathlib import Path

from src.chunking import recursive_chunks
from src.embeddings import Embedder
from src.fusion import reciprocal_rank_fusion, weighted_fusion
from src.generation import Generator
from src.lexical_search import LexicalSearch
from src.vector_store import VectorStore


class HybridRAGPipeline:
    def __init__(self, index_dir: str = "data/index", top_k: int = 3, fetch_k: int = 10):
        self.index_dir = index_dir
        self.top_k = top_k       # chunks finais entregues ao Claude
        self.fetch_k = fetch_k   # candidatos buscados em cada índice antes da fusão
        self.embedder = Embedder()
        self.generator = Generator()
        self.vector_store = VectorStore()
        self.lexical_search: LexicalSearch | None = None
        self.chunks: list[str] = []

    # --- Fase 1: indexação (constrói os DOIS índices) ---
    def index_file(self, path: str, chunk_size: int = 500, overlap: int = 60) -> int:
        file = Path(path)
        text = file.read_text(encoding="utf-8")
        self.chunks = recursive_chunks(text, chunk_size=chunk_size, overlap=overlap)

        vectors = self.embedder.embed(self.chunks)
        metadata = [{"source": file.name, "chunk": i} for i in range(len(self.chunks))]
        self.vector_store.add(self.chunks, vectors, metadata)

        self.lexical_search = LexicalSearch(self.chunks)
        return len(self.chunks)

    def save(self) -> None:
        self.vector_store.save(self.index_dir)

    def load(self) -> None:
        self.vector_store = VectorStore.load(self.index_dir)
        self.chunks = self.vector_store.texts
        self.lexical_search = LexicalSearch(self.chunks)

    # --- Fase 2: consulta híbrida ---
    def retrieve(self, question: str, method: str = "rrf", alpha: float = 0.5) -> list[dict]:
        query_vec = self.embedder.embed_one(question)
        semantic_results = self.vector_store.search(query_vec, k=self.fetch_k)
        lexical_results = self.lexical_search.search(question, k=self.fetch_k)

        if method == "rrf":
            return reciprocal_rank_fusion(semantic_results, lexical_results, k=self.top_k)
        elif method == "weighted":
            return weighted_fusion(semantic_results, lexical_results, alpha=alpha, k=self.top_k)
        elif method == "semantic":
            return semantic_results[: self.top_k]
        elif method == "lexical":
            return lexical_results[: self.top_k]
        else:
            raise ValueError(f"método desconhecido: {method}")

    def ask(self, question: str, method: str = "rrf", alpha: float = 0.5) -> dict:
        chunks = self.retrieve(question, method=method, alpha=alpha)
        answer = self.generator.answer(question, chunks)
        return {"question": question, "answer": answer, "sources": chunks, "method": method}
