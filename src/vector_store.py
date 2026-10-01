import json
from pathlib import Path

import numpy as np

class VectorStore:
    def __init__(self):
        self.texts: list[str] = []
        self.metadata: list[dict] = []
        self.vectors: np.ndarray | None = None

    def add(self, texts: list[str], vectors: np.ndarray, metadata: list[dict] | None = None):
        metadata = metadata or [{} for _ in texts]
        self.texts.extend(texts)
        self.metadata.extend(metadata)
        self.vectors = (
            vectors if self.vectors is None else np.vstack([self.vectors, vectors])
        )

    def search(self, query_vector: np.ndarray, k: int = 3) -> list[dict]:
        """Retorna os k chunks mais similares à pergunta."""
        scores = self.vectors @ query_vector
        top_idx = np.argsort(scores)[::-1][:k]
        return [
            {
                "index": int(i),
                "score": float(scores[i]),
                "text": self.texts[i],
                "metadata": self.metadata[i],
            }
            for i in top_idx
        ]

    def save(self, directory: str) -> None:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        np.save(path / "vectors.npy", self.vectors)
        (path / "texts.json").write_text(
            json.dumps({"texts": self.texts, "metadata": self.metadata}, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: str) -> "VectorStore":
        path = Path(directory)
        store = cls()
        store.vectors = np.load(path / "vectors.npy")
        data = json.loads((path / "texts.json").read_text(encoding="utf-8"))
        store.texts = data["texts"]
        store.metadata = data["metadata"]
        return store
