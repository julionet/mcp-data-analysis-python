import logging
from dataclasses import dataclass, field
from itertools import islice
from typing import Iterable, Iterator

import numpy as np

from src.chunking import Chunk
from src.config import EMBEDDING_MODEL, HF_TOKEN

BATCH_SIZE = 64
MAX_SEQ_LENGTH = 8192  # limite nativo do bge-m3

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Erro esperado, com mensagem já pronta para a pessoa."""


@dataclass
class EmbedStats:
    """Preenchido por `embed_chunks` à medida que os trechos são vetorizados."""

    count: int = 0
    token_total: int = 0
    token_min: int = 0
    token_max: int = 0
    over_limit: list[int] = field(default_factory=list)  # chunk_index dos trechos acima do limite

    def add(self, chunk_index: int, tokens: int, limit: int) -> None:
        self.count += 1
        self.token_total += tokens
        self.token_min = tokens if self.count == 1 else min(self.token_min, tokens)
        self.token_max = max(self.token_max, tokens)
        if tokens > limit:
            self.over_limit.append(chunk_index)


class Embedder:
    """Encapsula o modelo de embeddings local (carregado uma vez por processo)."""

    def __init__(
        self,
        model_name: str | None = None,
        batch_size: int = BATCH_SIZE,
        max_seq_length: int = MAX_SEQ_LENGTH,
    ):
        model_name = model_name or EMBEDDING_MODEL
        if not model_name:
            raise EmbeddingError("EMBEDDING_MODEL não definida. Copie .env.example para .env e preencha.")
        if batch_size <= 0 or max_seq_length <= 0:
            raise EmbeddingError("batch_size e max_seq_length devem ser maiores que zero.")

        # imports pesados só aqui, para importar este módulo ser barato
        import torch
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.batch_size = batch_size
        self.max_seq_length = max_seq_length
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        try:
            self.model = SentenceTransformer(model_name, device=self.device, token=HF_TOKEN)
        except Exception as e:
            reason = (str(e).strip().splitlines() or [type(e).__name__])[0].split(" (Request ID")[0].rstrip(".")
            raise EmbeddingError(
                f'Não foi possível carregar o modelo "{model_name}": {reason}. '
                "Confira EMBEDDING_MODEL, a rede e o HF_TOKEN."
            ) from None
        self.model.max_seq_length = max_seq_length
        get_dim = getattr(self.model, "get_embedding_dimension", None) or self.model.get_sentence_embedding_dimension
        self.dimension: int = get_dim()

    def check_dimension(self, expected: int) -> None:
        if self.dimension != expected:
            raise EmbeddingError(
                f'O modelo "{self.model_name}" gera vetores de {self.dimension} dimensões, '
                f"mas o banco usa {expected}. Trocar de dimensão exige nova migração."
            )

    def count_tokens(self, texts: list[str]) -> list[int]:
        """Nº de tokens de cada texto (sem truncar), com o tokenizer do modelo."""
        if not texts:
            return []
        encoded = self.model.tokenizer(texts, add_special_tokens=True, truncation=False)
        return [len(ids) for ids in encoded["input_ids"]]

    def embed(self, texts: list[str], batch_size: int | None = None) -> np.ndarray:
        """Retorna matriz (len(texts), dimensões) com vetores normalizados."""
        return self.model.encode(
            texts,
            batch_size=batch_size or self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


def embed_chunks(
    embedder: Embedder,
    chunks: Iterable[Chunk],
    batch_size: int | None = None,
    stats: EmbedStats | None = None,
) -> Iterator[tuple[Chunk, np.ndarray]]:
    """Vetoriza `Chunk.embedding_text` em lotes, em fluxo.

    Ao fim, se algum trecho passou de `max_seq_length` tokens, emite um único aviso
    (o modelo trunca o excedente; não bloqueia).
    """
    if stats is None:
        stats = EmbedStats()
    size = batch_size or embedder.batch_size
    iterator = iter(chunks)
    while batch := list(islice(iterator, size)):
        texts = [c.embedding_text for c in batch]
        for chunk, tokens in zip(batch, embedder.count_tokens(texts)):
            stats.add(chunk.chunk_index, tokens, embedder.max_seq_length)
        vectors = embedder.embed(texts, batch_size=size)
        yield from zip(batch, vectors)

    if stats.over_limit:
        indexes = ", ".join(str(i) for i in stats.over_limit)
        logger.warning(
            "Aviso: %d trecho(s) excedem %d tokens e serão truncados pelo modelo (chunk_index: %s).",
            len(stats.over_limit),
            embedder.max_seq_length,
            indexes,
        )
