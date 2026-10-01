from src.hybrid_rag import HybridRAGPipeline

QUERIES = [
    "E-5107",
    "posso trabalhar de casa",
    "erro E-4021 na VPN",
    "quanto posso gastar em refeição na viagem",
]

METHODS = ["semantic", "lexical", "weighted", "rrf"]


def main() -> None:
    rag = HybridRAGPipeline(top_k=3, fetch_k=10)
    rag.index_file("data/manual_colaborador.txt")
    rag.save()

    for query in QUERIES:
        print("=" * 70)
        print(f"PERGUNTA: {query}\n")
        for method in METHODS:
            results = rag.retrieve(query, method=method)
            print(f"[{method.upper()}]")
            for r in results:
                preview = r["text"].replace("\n", " ")[:60]
                print(f"  score={r['score']:.4f} | chunk {r['index']} | {preview}...")
        print()


if __name__ == "__main__":
    main()
