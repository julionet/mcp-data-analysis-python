from pathlib import Path

from src.chunking import recursive_chunks, sentence_chunks
from src.embeddings import Embedder
from src.vector_store import VectorStore

DOC_PATH = Path("data/manual_colaborador.txt")
INDEX_DIR = "data/index"

QUERIES = [
    "Quantos dias de férias eu posso tirar?",
    "Posso trabalhar de casa?",
    "Meu notebook não conecta na VPN, o que faço?",
    "Qual o limite de gasto com almoço em viagem?",
    "O que significa o erro E-5107?",
    "Qual o telefone do RH?",
]


def main() -> None:
    embedder = Embedder()

    # --- Indexação ---
    text = DOC_PATH.read_text(encoding="utf-8")
    #chunks = recursive_chunks(text, chunk_size=500, overlap=60)
    chunks = sentence_chunks(text, max_chars=500, overlap_sentences=1)
    vectors = embedder.embed(chunks)

    store = VectorStore()
    store.add(chunks, vectors, [{"source": DOC_PATH.name, "chunk": i} for i in range(len(chunks))])
    store.save(INDEX_DIR)

    print(f"Indexados {len(chunks)} chunks, matriz {vectors.shape}\n")

    # --- Consulta ---
    for query in QUERIES:
        query_vec = embedder.embed_one(query)
        results = store.search(query_vec, k=3)

        print("=" * 70)
        print(f"PERGUNTA: {query}")
        for rank, r in enumerate(results, start=1):
            preview = r["text"].replace("\n", " ")[:90]
            print(f"  {rank}. score={r['score']:.3f} | chunk {r['index']} | {preview}...")
        print()


if __name__ == "__main__":
    main()
