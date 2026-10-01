from pathlib import Path

from src.chunking import recursive_chunks
from src.embeddings import Embedder
from src.generation import Generator
from src.vector_store import VectorStore


class RAGPipeline:
    def __init__(self, index_dir: str = "data/index", top_k: int = 3):
        self.index_dir = index_dir
        self.top_k = top_k
        self.embedder = Embedder()
        self.generator = Generator()
        self.store = VectorStore()

    # --- Fase 1: indexação ---
    def index_file(self, path: str, chunk_size: int = 500, overlap: int = 60) -> int:
        file = Path(path)
        text = file.read_text(encoding="utf-8")
        chunks = recursive_chunks(text, chunk_size=chunk_size, overlap=overlap)
        vectors = self.embedder.embed(chunks)
        metadata = [{"source": file.name, "chunk": i} for i in range(len(chunks))]
        self.store.add(chunks, vectors, metadata)
        return len(chunks)

    def save(self) -> None:
        self.store.save(self.index_dir)

    def load(self) -> None:
        self.store = VectorStore.load(self.index_dir)

    # --- Fase 2: consulta ---
    def retrieve(self, question: str) -> list[dict]:
        query_vec = self.embedder.embed_one(question)
        return self.store.search(query_vec, k=self.top_k)

    def ask(self, question: str) -> dict:
        chunks = self.retrieve(question)
        answer = self.generator.answer(question, chunks)
        return {"question": question, "answer": answer, "sources": chunks}
