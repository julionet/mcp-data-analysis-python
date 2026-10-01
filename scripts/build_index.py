from src.rag import RAGPipeline


def main() -> None:
    rag = RAGPipeline()
    n = rag.index_file("data/manual_colaborador.txt")
    rag.save()
    print(f"Índice criado com {n} chunks em {rag.index_dir}")


if __name__ == "__main__":
    main()
