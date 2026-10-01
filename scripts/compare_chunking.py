from pathlib import Path

from sentence_transformers import SentenceTransformer

from src.chunking import (
    fixed_size_chunks,
    sentence_chunks,
    recursive_chunks,
    semantic_chunks,
)
from src.config import EMBEDDING_MODEL, HF_TOKEN


DOC_PATH = Path("data/manual_colaborador.txt")

def report(name: str, chunks: list[str], show: int = 3) -> None:
    sizes = [len(c) for c in chunks]
    print("=" * 70)
    print(f"{name}")
    print(
        f"chunks: {len(chunks)} | tamanho médio: {sum(sizes) // len(sizes)} "
        f"| mín: {min(sizes)} | máx: {max(sizes)}"
    )
    print("-" * 70)
    for i, chunk in enumerate(chunks[:show], start=1):
        print(f"[chunk {i}] ({len(chunk)} chars)")
        print(chunk)
        print()


def main() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    print(f"Documento: {len(text)} caracteres\n")

    report("1) TAMANHO FIXO (400, overlap 80)", fixed_size_chunks(text, 400, 80), show=-1)
    report("2) POR SENTENÇAS (max 400, overlap 1)", sentence_chunks(text, 400, 1), show=-1)
    report("3) RECURSIVA (400, overlap 60)", recursive_chunks(text, 400, 60), show=-1)

    print("Carregando modelo para chunking semântico...")
    model = SentenceTransformer(EMBEDDING_MODEL, token=HF_TOKEN)
    report("4) SEMÂNTICA (percentil 25)", semantic_chunks(text, model, 25), show=-1)


if __name__ == "__main__":
    main()
