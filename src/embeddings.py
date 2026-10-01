import numpy as np
from sentence_transformers import SentenceTransformer

from src.config import EMBEDDING_MODEL

class Embedder:
    """Encapsula o modelo de embeddings local."""

    def __init__(self, model_name: str = EMBEDDING_MODEL):
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        """Retorna matriz (len(texts), dimensões) com vetores normalizados."""
        return self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]