import argparse
import sys

from src.chunking import MAX_CHARS, OVERLAP_CHARS, STRATEGIES, Chunk, chunk_pages
from src.loaders import LoaderError, inspect_document, iter_pages


def _show_count(value: str) -> int | None:
    """None = mostrar todos."""
    if value == "all":
        return None
    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError('use um número ou "all"') from None
    if count < 0:
        raise argparse.ArgumentTypeError("não pode ser negativo")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.chunk_document",
        description="Divide um TXT, MD ou PDF em trechos e mostra o resultado (apoio ao teste da F03).",
    )
    parser.add_argument("arquivo")
    parser.add_argument("--strategy", choices=STRATEGIES, default="structured")
    parser.add_argument("--max-chars", type=int, default=MAX_CHARS)
    parser.add_argument("--overlap", type=int, default=OVERLAP_CHARS)
    parser.add_argument("--show", type=_show_count, default=5, metavar="N|all")
    args = parser.parse_args(argv)

    try:
        info = inspect_document(args.arquivo)
        model = None
        if args.strategy == "semantic":
            from sentence_transformers import SentenceTransformer

            from src.config import EMBEDDING_MODEL, HF_TOKEN

            model = SentenceTransformer(EMBEDDING_MODEL, token=HF_TOKEN)

        chunks = chunk_pages(
            iter_pages(args.arquivo),
            args.strategy,
            model=model,
            max_chars=args.max_chars,
            overlap_chars=args.overlap,
        )
        count = total = over = 0
        smallest = largest = 0
        shown: list[Chunk] = []
        for chunk in chunks:  # em fluxo: guarda só os trechos que serão mostrados
            size = len(chunk.content)
            count += 1
            total += size
            over += size > args.max_chars
            smallest = size if count == 1 else min(smallest, size)
            largest = max(largest, size)
            if args.show is None or len(shown) < args.show:
                shown.append(chunk)
    except (LoaderError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1

    pages = f"{info.page_count} página" + ("s" if info.page_count != 1 else "")
    print(f"Arquivo:    {info.filename} ({info.file_type}, {pages})")
    print(f"Estratégia: {args.strategy} (max_chars={args.max_chars}, overlap_chars={args.overlap})")
    if count:
        print(
            f"Trechos:    {count} | tamanho mín {smallest} · média {total // count} · "
            f"máx {largest} | acima do limite: {over}"
        )
    else:
        print("Trechos:    0")
    for chunk in shown:
        section = chunk.section or "—"
        print(
            f"--- Trecho {chunk.chunk_index} | página {chunk.page} | seção: {section} "
            f"| {len(chunk.content)} caracteres ---"
        )
        print(chunk.content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
