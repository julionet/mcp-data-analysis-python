import argparse
import itertools
import sys
import time
from pathlib import Path

from src import db
from src.folder_ingestion import ConfirmUnavailable, Reporter


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


def _print_file_result(result) -> int:
    info = result.info
    pages = f"{info.page_count} página" + ("s" if info.page_count != 1 else "")
    print(f"Arquivo:    {result.path} ({info.file_type}, {pages})")
    if result.outcome == "unchanged":
        print(f"Resultado:  já cadastrado, sem mudanças (documento id {result.document_id})")
    elif result.outcome == "duplicate":
        note = " (versão anterior removida)" if result.replaced_previous else ""
        print(f"Resultado:  duplicado de {result.duplicate_of} (nada cadastrado){note}")
    else:
        label = "atualizado (versão anterior substituída)" if result.outcome == "updated" else "cadastrado"
        print(f"Resultado:  {label}")
        print(f"Documento:  id {result.document_id} | {result.chunk_count} trechos | páginas 1–{info.page_count}")
        note = "registrado em app_meta" if result.model_registered else "confere com o registro"
        print(f"Modelo:     {result.model_name} ({note})")
        print(f"Tempo:      {_fmt(result.elapsed)} s")
    return 0


_LABELS = {
    "created": "cadastrado",
    "updated": "atualizado",
    "unchanged": "sem mudanças",
    "adopted": "vinculado",
    "duplicate": "duplicado",
    "absent": "ausente",
    "removed": "removido",
    "failed": "falhou",
    "ignored": "ignorado",
}
_SINGULAR = {
    "created": "cadastrado",
    "updated": "atualizado",
    "adopted": "vinculado",
    "duplicate": "duplicado",
    "absent": "ausente",
    "removed": "removido",
    "failed": "falhou",
    "ignored": "ignorado",
}
_PLURAL = {
    "created": "cadastrados",
    "updated": "atualizados",
    "adopted": "vinculados",
    "duplicate": "duplicados",
    "absent": "ausentes",
    "removed": "removidos",
    "failed": "falharam",
    "ignored": "ignorados",
}


def _count_label(n: int, outcome: str) -> str:
    if outcome in ("unchanged",):
        return f"{n} sem mudanças"
    return f"{n} {(_SINGULAR if n == 1 else _PLURAL)[outcome]}"


def _file_detail(item) -> str:
    if item.outcome == "created":
        return f"{item.chunk_count} trechos"
    if item.outcome == "updated":
        return f"{item.chunk_count} trechos (versão anterior substituída)"
    if item.outcome == "adopted":
        return "arquivo avulso adotado pela pasta"
    if item.outcome == "absent":
        return "não existe mais em disco (use --prune para remover da base)"
    return item.detail


class _FolderReporter(Reporter):
    """Progresso em stderr e, antes da confirmação do --prune, a lista de arquivos em stdout."""

    def __init__(self) -> None:
        self.progress: _Progress | None = None
        self.files_printed = False

    def file_start(self, index: int, total: int, rel: str):
        print(f"[{index}/{total}] {rel}", file=sys.stderr, flush=True)
        self.progress = _Progress()
        return self.progress

    def file_end(self) -> None:
        if self.progress:
            self.progress.finish()
            self.progress = None

    def before_prune(self, result) -> None:
        _print_folder_header(result)
        _print_folder_files(result)
        self.files_printed = True


def _print_folder_header(result) -> None:
    status = "registrada agora" if result.registered_now else "já registrada"
    print(f"Pasta:      {result.folder} ({status} | recursiva: {'sim' if result.recursive else 'não'})")
    print(f"Arquivos:   {result.accepted} aceitos | {len(result.ignored)} ignorados")


def _print_folder_files(result) -> None:
    items = sorted([*result.files, *result.ignored], key=lambda f: f.path)
    if result.accepted == 0 and not result.files and not result.error:
        print(f"Nenhum arquivo TXT, MD ou PDF encontrado em {result.folder}.")
    if items:
        print()
        width = min(max(len(f.path) for f in items), 40)
        for item in items:
            print(f"  {_LABELS[item.outcome]:<13} {item.path:<{width}}  {_file_detail(item)}".rstrip())


def _confirm_prune(folder: str, paths: list[str], folder_missing: bool) -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ConfirmUnavailable()
    print()
    print("Documentos ausentes da pasta (arquivo não existe mais em disco):")
    for path in paths:
        print(f"  {path}")
    if folder_missing:
        question = (
            f"A pasta {folder} não foi encontrada em disco (unidade desmontada?). "
            f"Todos os {len(paths)} documentos dela seriam removidos. Remover? [s/N] "
        )
    else:
        question = f"Remover {len(paths)} documento(s) da base? [s/N] "
    try:
        return input(question).strip().lower() == "s"
    except EOFError:
        return False


def _print_folder_summary(result, reporter: _FolderReporter) -> None:
    if result.error:
        print(result.error, file=sys.stderr)
        return
    if not reporter.files_printed:
        _print_folder_header(result)
        _print_folder_files(result)
    if result.prune_status == "removed":
        print(f"Removido:   {result.count('removed')} documento(s)")
    elif result.prune_status == "none":
        print("Nenhum documento ausente.")
    elif result.prune_status == "declined":
        print("Nada foi removido.")
    elif result.prune_status == "unavailable":
        print("--prune exige confirmação em um terminal interativo; nada foi removido.", file=sys.stderr)
    elif result.prune_status == "cancelled":
        print("Remoção cancelada.", file=sys.stderr)

    counts = [(result.count(o), o) for o in ("created", "updated", "unchanged", "adopted", "duplicate", "absent", "removed", "failed")]
    parts = [_count_label(n, o) for n, o in counts if n]
    if result.ignored:
        parts.append(_count_label(len(result.ignored), "ignored"))
    print()
    print(f"Resumo:     {', '.join(parts) if parts else 'nenhum arquivo'}")
    if result.out_of_scope:
        print(f"Aviso:      {result.out_of_scope} documento(s) em subpastas não são mais atualizados (a pasta não é recursiva).")
    if result.interrupted:
        print("Atualização interrompida; os arquivos já concluídos foram mantidos.", file=sys.stderr)
    if result.fatal:
        print(result.fatal, file=sys.stderr)
    print(f"Tempo:      {_fmt(result.elapsed)} s")


def _run_folder_command(runner, reporter: _FolderReporter) -> int:
    """Imprime os resultados de ingest/reindex e devolve o código de saída."""
    problem = False
    try:
        for result in runner:
            _print_folder_summary(result, reporter)
            reporter.files_printed = False
            problem = problem or result.has_problem
    except KeyboardInterrupt:
        print("Atualização interrompida; os arquivos já concluídos foram mantidos.", file=sys.stderr)
        return 1
    return 1 if problem else 0


def cmd_ingest(args: argparse.Namespace) -> int:
    # imports tardios: ingestion/embeddings não devem pesar nos comandos init-db e check
    from src.embeddings import EmbeddingError
    from src.folder_ingestion import FolderError, ingest_folder
    from src.ingestion import IngestError, ingest_file
    from src.loaders import LoaderError

    target = Path(args.arquivo)
    if target.is_dir():
        reporter = _FolderReporter()
        try:
            result = ingest_folder(
                target, args.recursive, args.force, args.prune, reporter, _confirm_prune
            )
        except (FolderError, LoaderError, EmbeddingError, db.DbError) as e:
            print(str(e), file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("Atualização interrompida; os arquivos já concluídos foram mantidos.", file=sys.stderr)
            return 1
        return _run_folder_command(iter([result]), reporter)

    option = "--prune" if args.prune else None
    if args.recursive is not None:
        option = "--recursive" if args.recursive else "--no-recursive"
    if option:
        print(f"{option} só se aplica a pastas.", file=sys.stderr)
        return 1

    progress = _Progress()
    try:
        result = ingest_file(args.arquivo, progress, args.force)
    except KeyboardInterrupt:
        progress.finish()
        print("Cadastro interrompido; nada foi gravado.", file=sys.stderr)
        return 1
    except (IngestError, LoaderError, EmbeddingError, db.DbError) as e:
        progress.finish()
        print(str(e), file=sys.stderr)
        return 1
    progress.finish()
    return _print_file_result(result)


def cmd_reindex(args: argparse.Namespace) -> int:
    from src.embeddings import EmbeddingError
    from src.folder_ingestion import reindex_folders

    reporter = _FolderReporter()
    try:
        runner = reindex_folders(None if args.all else args.pasta, args.prune, reporter, _confirm_prune)
        first = next(runner, None)
        if first is None:
            print("Nenhuma pasta registrada. Cadastre com: python -m src.cli ingest <pasta>")
            return 0
        return _run_folder_command(itertools.chain([first], runner), reporter)
    except (EmbeddingError, db.DbError) as e:
        print(str(e), file=sys.stderr)
        return 1


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


def _table(headers: list[str], rows: list[list[str]], right: set[int] = frozenset()) -> None:
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]

    def line(cells: list[str]) -> str:
        return "  ".join(c.rjust(widths[i]) if i in right else c.ljust(widths[i]) for i, c in enumerate(cells)).rstrip()

    print(line(headers))
    for row in rows:
        print(line(row))


def cmd_folders(args: argparse.Namespace) -> int:
    from src import management_service

    try:
        stats = management_service.list_folders()
    except db.DbError as e:
        print(str(e), file=sys.stderr)
        return 1
    if not any(s.path for s in stats):
        print("Nenhuma pasta registrada. Cadastre com: python -m src.cli ingest <pasta>")
    if not stats:
        return 0
    rows = [
        [
            s.path or "(avulsos)",
            "—" if s.recursive is None else ("sim" if s.recursive else "não"),
            str(s.documents),
            str(s.chunks),
            s.last_indexed_at.astimezone().strftime("%Y-%m-%d %H:%M") if s.last_indexed_at else "—",
        ]
        for s in stats
    ]
    _table(["PASTA", "RECURSIVA", "DOCS", "TRECHOS", "ÚLTIMA INDEXAÇÃO"], rows, right={2, 3})
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    from src import management_service

    try:
        docs = management_service.list_documents(args.folder)
    except db.DbError as e:
        print(str(e), file=sys.stderr)
        return 1
    if not docs:
        if args.folder:
            print(f"Nenhum documento em {Path(args.folder).resolve()}.")
        else:
            print("Nenhum documento na base.")
        return 0
    rows = [[d.source_path, d.file_type, str(d.pages), str(d.chunks), d.status] for d in docs]
    _table(["CAMINHO", "TIPO", "PÁG", "TRECHOS", "STATUS"], rows, right={2, 3})
    print()
    print(f"{len(docs)} documento(s), {sum(d.chunks for d in docs)} trecho(s).")
    return 0


DELETE_LIST_LIMIT = 20


def _confirm_delete(kind: str, target: str, paths: list[str], chunks: int) -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ConfirmUnavailable()
    label = "Pasta" if kind == "folder" else "Documento"
    print(f"{label}: {target} ({len(paths)} documento(s), {chunks} trecho(s))")
    if kind == "folder":
        for path in paths[:DELETE_LIST_LIMIT]:
            print(f"  {path}")
        if len(paths) > DELETE_LIST_LIMIT:
            print(f"  … e mais {len(paths) - DELETE_LIST_LIMIT}")
    print("Os arquivos no disco não serão apagados." + (" A pasta deixará de ser registrada." if kind == "folder" else ""))
    try:
        return input("Remover? [s/N] ").strip().lower() == "s"
    except EOFError:
        return False


def cmd_delete(args: argparse.Namespace) -> int:
    from src import management_service

    try:
        result = management_service.delete_target(args.alvo, _confirm_delete)
    except ConfirmUnavailable:
        print("delete exige confirmação em um terminal interativo; nada foi removido.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Remoção cancelada.", file=sys.stderr)
        return 1
    except (management_service.ManagementError, db.DbError) as e:
        print(str(e), file=sys.stderr)
        return 1
    if result.status == "declined":
        print("Nada foi removido.")
        return 0
    print(f"Removido: {result.documents} documento(s), {result.chunks} trecho(s).")
    if result.kind == "folder":
        print(f"Pasta {result.target} removida do registro.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.cli", description="RAG Training — CLI")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init-db", help="aplica o esquema do banco (idempotente)")
    sub.add_parser("check", help="verifica configuração e banco")
    ingest = sub.add_parser("ingest", help="cadastra ou atualiza um arquivo TXT, MD ou PDF, ou uma pasta")
    ingest.add_argument("arquivo", help="arquivo ou pasta")
    ingest.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=None, help="percorre as subpastas (só pasta)")
    ingest.add_argument("--force", action="store_true", help="revetoriza mesmo sem mudança")
    ingest.add_argument("--prune", action="store_true", help="remove da base, com confirmação, o que sumiu da pasta")

    reindex = sub.add_parser("reindex", help="reprocessa pastas registradas, só o que mudou")
    reindex.add_argument("pasta", nargs="?")
    reindex.add_argument("--all", action="store_true", help="todas as pastas registradas")
    reindex.add_argument("--prune", action="store_true", help="remove da base, com confirmação, o que sumiu da pasta")

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

    sub.add_parser("folders", help="lista as pastas registradas")
    list_cmd = sub.add_parser("list", help="lista os documentos da base")
    list_cmd.add_argument("--folder", help="mostra só os documentos dentro desta pasta")
    delete = sub.add_parser("delete", help="remove um documento ou uma pasta registrada, com confirmação")
    delete.add_argument("alvo", help="arquivo ou pasta registrada")

    args = parser.parse_args(argv)
    if args.command == "reindex":
        if args.all and args.pasta:
            parser.error("Use <pasta> ou --all, não os dois.")
        if not args.all and not args.pasta:
            parser.error("Informe <pasta> ou --all.")
    commands = {
        "init-db": cmd_init_db,
        "check": cmd_check,
        "ingest": cmd_ingest,
        "reindex": cmd_reindex,
        "search": cmd_search,
        "ask": cmd_ask,
        "folders": cmd_folders,
        "list": cmd_list,
        "delete": cmd_delete,
    }
    if args.command is None:
        parser.print_help()
        return 0
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
