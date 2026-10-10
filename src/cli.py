import argparse
import sys
import time

from src import db


def cmd_init_db(args: argparse.Namespace) -> int:
    try:
        for line in db.init_db():
            print(line)
    except db.DbError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    lines, failures = db.check_environment()
    for line in lines:
        print(line)
    return 1 if failures else 0


def _fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


class _Progress:
    """Progresso em stderr: linha reescrita no terminal; uma linha a cada ~10% fora dele."""

    def __init__(self) -> None:
        self.tty = sys.stderr.isatty()
        self.started: float | None = None
        self.last_draw = 0.0
        self.next_percent = 10
        self.drawn = False

    def __call__(self, page: int, total: int, chunks: int, rate: float) -> None:
        if self.started is None:
            self.started = time.perf_counter() - chunks / rate if rate else time.perf_counter()
        percent = page * 100 // total if total else 100
        if self.tty:
            now = time.perf_counter()
            if now - self.last_draw < 0.2:
                return
            self.last_draw = now
        elif percent < self.next_percent:
            return
        else:
            self.next_percent = percent // 10 * 10 + 10

        remaining = ""
        if page and total > page:
            seconds = (time.perf_counter() - self.started) / page * (total - page)
            remaining = f" | restante ~{_fmt(seconds / 60) + ' min' if seconds >= 90 else str(int(seconds)) + ' s'}"
        line = (
            f"Lendo e vetorizando: página {page}/{total} | trechos {chunks} | "
            f"{_fmt(rate)} trechos/s{remaining}"
        )
        if self.tty:
            print("\r" + line + "\x1b[K", end="", file=sys.stderr, flush=True)
            self.drawn = True
        else:
            print(line, file=sys.stderr, flush=True)

    def finish(self) -> None:
        if self.drawn:
            print(file=sys.stderr)
            self.drawn = False


def cmd_ingest(args: argparse.Namespace) -> int:
    # imports tardios: ingestion/embeddings não devem pesar nos comandos init-db e check
    from src.embeddings import EmbeddingError
    from src.ingestion import IngestError, ingest_file
    from src.loaders import LoaderError

    progress = _Progress()
    try:
        result = ingest_file(args.arquivo, progress)
    except KeyboardInterrupt:
        progress.finish()
        print("Cadastro interrompido; nada foi gravado.", file=sys.stderr)
        return 1
    except (IngestError, LoaderError, EmbeddingError, db.DbError) as e:
        progress.finish()
        print(str(e), file=sys.stderr)
        return 1
    progress.finish()

    info = result.info
    pages = f"{info.page_count} página" + ("s" if info.page_count != 1 else "")
    print(f"Arquivo:    {result.path} ({info.file_type}, {pages})")
    if result.outcome == "unchanged":
        print(f"Resultado:  já cadastrado, sem mudanças (documento id {result.document_id})")
    elif result.outcome == "duplicate":
        print(f"Resultado:  duplicado de {result.duplicate_of} (nada cadastrado)")
    else:
        print("Resultado:  cadastrado")
        print(f"Documento:  id {result.document_id} | {result.chunk_count} trechos | páginas 1–{info.page_count}")
        note = "registrado em app_meta" if result.model_registered else "confere com o registro"
        print(f"Modelo:     {result.model_name} ({note})")
        print(f"Tempo:      {_fmt(result.elapsed)} s")
    return 0


SNIPPET_CHARS = 240


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("use um número inteiro") from None
    if number <= 0:
        raise argparse.ArgumentTypeError("deve ser maior que zero")
    return number


def _hit_origin(hit, method: str) -> str:
    if method == "semantic":
        return f"similaridade {_fmt(hit.semantic_score, 2)}"
    if method == "lexical":
        return f"textual (ts_rank_cd {_fmt(hit.lexical_score, 2)})"
    parts = []
    if hit.semantic_rank is not None:
        parts.append(f"semântico #{hit.semantic_rank} ({_fmt(hit.semantic_score, 2)})")
    if hit.lexical_rank is not None:
        parts.append(f"textual #{hit.lexical_rank} ({_fmt(hit.lexical_score, 2)})")
    return " · ".join(parts)


def cmd_search(args: argparse.Namespace) -> int:
    # imports tardios: a busca não deve pesar nos comandos init-db e check
    from src.embeddings import EmbeddingError
    from src.search_service import SearchError, run_search

    try:
        result = run_search(args.pergunta, args.method, args.top_k, args.fetch_k, args.folder)
    except (SearchError, EmbeddingError, db.DbError) as e:
        print(str(e), file=sys.stderr)
        return 1

    if result.status == "empty_base":
        print("A base está vazia. Cadastre um arquivo com: python -m src.cli ingest <arquivo>")
        return 0
    if result.status == "no_documents_in_folder":
        print(f"Nenhum documento cadastrado em {result.folder}.")
        return 0

    print(f"Pergunta:  {args.pergunta.strip()}")
    print(
        f"Método:    {result.method} | top-k {result.top_k} | fetch-k {result.fetch_k} | "
        f"pasta: {result.folder or '(todas)'}"
    )
    if not result.hits:
        print("Nenhum trecho encontrado.")
        return 0
    print(f"Resultados: {len(result.hits)} em {_fmt(result.elapsed)} s")
    for position, hit in enumerate(result.hits, 1):
        score = _fmt(hit.score, 4) if result.method == "rrf" else _fmt(hit.score, 2)
        print()
        print(f"#{position}  score {score} | {_hit_origin(hit, result.method)}")
        print(f"    {hit.filename} | página {hit.page} | {hit.section or '—'}")
        text = hit.content if args.full else " ".join(hit.content.split())
        if not args.full and len(text) > SNIPPET_CHARS:
            text = text[:SNIPPET_CHARS].rstrip() + " …"
        print("    " + text.replace("\n", "\n    "))
    return 0


def _print_ask_header(question: str, result) -> None:
    print(f"Pergunta:  {question.strip()}")
    print(
        f"Método:    {result.method} | top-k {result.top_k} | fetch-k {result.fetch_k} | "
        f"pasta: {result.folder or '(todas)'}"
    )


def cmd_ask(args: argparse.Namespace) -> int:
    # imports tardios: o ask não deve pesar nos comandos init-db e check
    from src.answer_service import AskError, run_ask
    from src.embeddings import EmbeddingError
    from src.generation import GenerationError
    from src.search_service import SearchError

    header_done = False

    def before_send(search) -> None:
        nonlocal header_done
        _print_ask_header(args.pergunta, search)
        header_done = True
        print("Os trechos encontrados serão enviados ao Claude (serviço externo).", file=sys.stderr, flush=True)  # R11

    try:
        result = run_ask(args.pergunta, args.method, args.top_k, args.fetch_k, args.folder, before_send)
    except KeyboardInterrupt:
        print("Pergunta interrompida.", file=sys.stderr)
        return 1
    except (AskError, SearchError, GenerationError, EmbeddingError, db.DbError) as e:
        print(str(e), file=sys.stderr)
        return 1

    search = result.search
    if search.status == "empty_base":
        print("A base está vazia. Cadastre um arquivo com: python -m src.cli ingest <arquivo>")
        return 0
    if search.status == "no_documents_in_folder":
        print(f"Nenhum documento cadastrado em {search.folder}.")
        return 0

    if not header_done:  # busca sem trechos: o Claude não foi chamado
        _print_ask_header(args.pergunta, search)
    print()
    print("Resposta:")
    print(result.answer)
    if result.truncated:
        print("A resposta foi cortada pelo limite de tokens.", file=sys.stderr)
    if result.sources:
        print()
        print("Fontes:")
        for number, hit in result.sources:
            print(f"[{number}] {hit.filename} | página {hit.page} | {hit.section or '—'}")
    elif result.cited_none:
        print()
        print("Fontes: o Claude não citou nenhum trecho.")
        print("A resposta não traz citações [n]; confira nos documentos.", file=sys.stderr)
    if header_done:
        total = search.elapsed + result.answer_elapsed
        print(
            f"Tempo: {_fmt(total)} s (busca {_fmt(search.elapsed)} s, resposta {_fmt(result.answer_elapsed)} s)"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.cli", description="RAG Training — CLI")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init-db", help="aplica o esquema do banco (idempotente)")
    sub.add_parser("check", help="verifica configuração e banco")
    ingest = sub.add_parser("ingest", help="cadastra um arquivo TXT, MD ou PDF")
    ingest.add_argument("arquivo")

    search = sub.add_parser("search", help="mostra os trechos mais relevantes para uma pergunta")
    search.add_argument("pergunta")
    search.add_argument("--method", choices=("rrf", "semantic", "lexical"), default="rrf")
    search.add_argument("--top-k", type=_positive_int, default=5)
    search.add_argument("--fetch-k", type=_positive_int, default=20)
    search.add_argument("--folder", help="limita a busca a documentos dentro desta pasta")
    search.add_argument("--full", action="store_true", help="mostra o trecho inteiro")

    ask = sub.add_parser("ask", help="responde a uma pergunta com base nos documentos, citando as fontes")
    ask.add_argument("pergunta")
    ask.add_argument("--method", choices=("rrf", "semantic", "lexical"), default="rrf")
    ask.add_argument("--top-k", type=_positive_int, default=5)
    ask.add_argument("--fetch-k", type=_positive_int, default=20)
    ask.add_argument("--folder", help="limita a busca a documentos dentro desta pasta")

    args = parser.parse_args(argv)
    commands = {
        "init-db": cmd_init_db,
        "check": cmd_check,
        "ingest": cmd_ingest,
        "search": cmd_search,
        "ask": cmd_ask,
    }
    if args.command is None:
        parser.print_help()
        return 0
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
