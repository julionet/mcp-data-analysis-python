import sys

from src.rag import RAGPipeline


def main() -> None:
    if len(sys.argv) < 2:
        print('Uso: python -m scripts.ask "sua pergunta"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])

    rag = RAGPipeline()
    rag.load()
    result = rag.ask(question)

    print("=" * 70)
    print(f"PERGUNTA: {result['question']}\n")
    print("RESPOSTA:")
    print(result["answer"])
    print("\nFONTES RECUPERADAS:")
    for i, s in enumerate(result["sources"], start=1):
        preview = s["text"].replace("\n", " ")[:80]
        print(f"  [{i}] score={s['score']:.3f} | chunk {s['metadata']['chunk']} | {preview}...")


if __name__ == "__main__":
    main()
