import re

from rank_bm25 import BM25Okapi

# Palavras muito comuns em português que quase não ajudam a diferenciar chunks
STOPWORDS_PT = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "é", "em",
    "um", "uma", "uns", "umas", "para", "com", "no", "na", "nos", "nas",
    "por", "que", "se", "ao", "aos", "às", "à", "seu", "sua", "ou",
}


def tokenize(text: str) -> list[str]:
    """Extrai tokens alfanuméricos, preservando códigos como 'e-5107' e
    'sku-882' (o hífen entre números e letras não é separado)."""
    text = text.lower()
    tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text)
    return [t for t in tokens if t not in STOPWORDS_PT]


class LexicalSearch:
    def __init__(self, chunks: list[str]):
        self.chunks = chunks
        self.tokenized_chunks = [tokenize(c) for c in chunks]
        self.bm25 = BM25Okapi(self.tokenized_chunks)

    def search(self, query: str, k: int = 3) -> list[dict]:
        query_tokens = tokenize(query)
        scores = self.bm25.get_scores(query_tokens)
        top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        return [
            {"index": int(i), "score": float(scores[i]), "text": self.chunks[i]}
            for i in top_idx
        ]
