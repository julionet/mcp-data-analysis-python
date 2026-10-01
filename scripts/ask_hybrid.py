import sys

from src.hybrid_rag import HybridRAGPipeline


def main() -> None:
    if len(sys.argv) < 2:
        print('Uso: python -m scripts.ask_hybrid "sua pergunta" [método]')
        print("métodos: rrf (padrão), weighted, semantic, lexical")
        sys.exit(1)

    method = "rrf"
    args = sys.argv[1:]
    if args[-1] in ("rrf", "weighted", "semantic", "lexical"):
        method = args[-1]
        args = args[:-1]
    question = " ".join(args)

    rag = HybridRAGPipeline()
    rag.load()
    result = rag.ask(question, method=method)

    print("=" * 70)
    print(f"PERGUNTA: {result['question']}  [método: {result['method']}]\n")
    print("RESPOSTA:")
    print(result["answer"])
    print("\nFONTES:")
    for i, s in enumerate(result["sources"], start=1):
        preview = s["text"].replace("\n", " ")[:80]
        print(f"  [{i}] score={s['score']:.4f} | chunk {s['index']} | {preview}...")


if __name__ == "__main__":
    main()
