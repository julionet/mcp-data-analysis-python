import argparse
import sys

from src.loaders import LoaderError, Page, inspect_document, iter_pages

PREVIEW_CHARS = 300


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.read_document",
        description="Lê um TXT ou PDF e mostra o resultado da leitura (apoio ao teste da F02).",
    )
    parser.add_argument("arquivo")
    parser.add_argument("--page", type=int, help="mostra o texto completo da página N")
    args = parser.parse_args(argv)

    try:
        info = inspect_document(args.arquivo)
        if args.page is not None and not 1 <= args.page <= info.page_count:
            print(f"Página {args.page} não existe (o documento tem {info.page_count}).", file=sys.stderr)
            return 1

        shown: Page | None = None
        empty = 0
        for page in iter_pages(args.arquivo):
            if args.page is not None:
                if page.number == args.page:
                    shown = page
                    break  # para de converter ao chegar na página pedida
                continue
            empty += not page.text
            shown = shown or page
    except LoaderError as e:
        print(str(e), file=sys.stderr)
        return 1

    pages = str(info.page_count) + (f" ({empty} sem texto)" if empty else "")
    print(f"Arquivo:  {info.filename}")
    print(f"Tipo:     {info.file_type}")
    print(f"SHA-256:  {info.sha256}")
    print(f"Páginas:  {pages}")
    if shown is not None:
        text = shown.text
        if args.page is None and len(text) > PREVIEW_CHARS:
            text = text[:PREVIEW_CHARS] + "…"
        print(f"--- Página {shown.number} ({len(shown.text)} caracteres) ---")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
