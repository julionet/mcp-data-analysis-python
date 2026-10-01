from pathlib import Path

from src.chunking import recursive_chunks
from src.embeddings import Embedder
from src.lexical_search import LexicalSearch
from src.vector_store import VectorStore

DOC_PATH = Path("data/manual_colaborador.txt")

QUERIES = [
    "E-5107",
    "erro E-4021",
    "posso trabalhar de casa",
    "quanto posso gastar em refeição na viagem",
    "phishing",
]


def main() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    chunks = recursive_chunks(text, chunk_size=500, overlap=60)

    # Busca semântica
    embedder = Embedder()
    vectors = embedder.embed(chunks)
    semantic_store = VectorStore()
    semantic_store.add(chunks, vectors)

    # Busca lexical
    lexical = LexicalSearch(chunks)

    for query in QUERIES:
        print("=" * 70)
        print(f"PERGUNTA: {query}\n")

        query_vec = embedder.embed_one(query)
        sem_results = semantic_store.search(query_vec, k=3)
        lex_results = lexical.search(query, k=3)

        print("SEMÂNTICA:")
        for r in sem_results:
            preview = r["text"].replace("\n", " ")[:70]
            print(f"  score={r['score']:.3f} | chunk {r['index']} | {preview}...")

        print("LEXICAL (BM25):")
        for r in lex_results:
            preview = r["text"].replace("\n", " ")[:70]
            print(f"  score={r['score']:.3f} | chunk {r['index']} | {preview}...")
        print()


if __name__ == "__main__":
    main()
