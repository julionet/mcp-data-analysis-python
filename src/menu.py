import argparse
import sys

from src import db

MENU = """=== RAG Training ===
1) Adicionar/indexar pasta
2) Reindexar uma pasta
3) Reindexar todas as pastas
4) Listar pastas e documentos
5) Fazer uma pergunta
6) Remover pasta ou documento
7) Verificar ambiente
0) Sair"""

METHODS = ("rrf", "semantic", "lexical")
INITIAL_METHOD = "rrf"
CONVERSATION_HELP = "Comandos: /metodo <rrf|semantic|lexical>, /pasta, /sair"
CANCELLED = "Operação cancelada."


def _ask(prompt: str) -> str:
    return input(prompt).strip()


def _choose_folder(allow_all: bool = False, empty_is_all: bool = False) -> str | None:
    """Lista numerada das pastas registradas (F10, T6). None = cancelou; "" = todas as pastas."""
    from src import management_service

    try:
        folders = [s.path for s in management_service.list_folders() if s.path]
    except db.DbError as e:
        print(str(e), file=sys.stderr)
        return None
    if not folders:
        print("Nenhuma pasta registrada. Cadastre com a opção 1 do menu.")
        return None
    print("Pastas registradas:")
    for number, path in enumerate(folders, 1):
        print(f"  {number}) {path}")
    if allow_all:
        print("  0) (todas)")
    hint = "Enter = todas" if empty_is_all else "Enter cancela"
    answer = _ask(f"Escolha o número da pasta ({hint}): ")
    if not answer:
        return "" if empty_is_all else None
    if allow_all and answer == "0":
        return ""
    if answer.isdigit() and 1 <= int(answer) <= len(folders):
        return folders[int(answer) - 1]
    print(CANCELLED)
    return None


def _conversation() -> None:
    """Modo conversa (T9): perguntas independentes, com método e pasta guardados na sessão."""
    from src import cli
    from src.retrieval import FETCH_K, TOP_K
    from src.search_service import EmbedderCache

    method = INITIAL_METHOD
    folder: str | None = None
    cache = EmbedderCache()
    print(f"Modo conversa | método: {method} | pasta: (todas)")
    print(CONVERSATION_HELP)
    while True:
        try:
            line = _ask("Pergunta> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if not line.startswith("/"):
            cli._ask_and_print(line, method, TOP_K, FETCH_K, folder, cache)
            continue
        command, _, argument = line.partition(" ")
        argument = argument.strip()
        if command == "/sair":
            return
        if command == "/metodo":
            if not argument:
                print(f"Método atual: {method}")
            elif argument in METHODS:
                method = argument
                print(f"Método: {method}")
            else:
                print("Método inválido. Use rrf, semantic ou lexical.")
        elif command == "/pasta":
            try:
                chosen = _choose_folder(allow_all=True)
            except (EOFError, KeyboardInterrupt):
                print()
                continue
            if chosen is not None:
                folder = chosen or None
                print(f"Pasta: {folder or '(todas)'}")
        else:
            print(CONVERSATION_HELP)


def _action(choice: str) -> None:
    from src import cli

    def run(command, **kwargs) -> None:
        command(argparse.Namespace(**kwargs))

    if choice == "1":
        path = _ask("Caminho da pasta: ")
        if not path:
            print(CANCELLED)
            return
        run(cli.cmd_ingest, arquivo=path, recursive=None, force=False, prune=False)
    elif choice == "2":
        path = _choose_folder()
        if path:
            run(cli.cmd_reindex, pasta=path, all=False, prune=False)
    elif choice == "3":
        run(cli.cmd_reindex, pasta=None, all=True, prune=False)
    elif choice == "4":
        run(cli.cmd_folders)
        print()
        path = _choose_folder(empty_is_all=True)
        if path is not None:
            run(cli.cmd_list, folder=path or None)
    elif choice == "5":
        _conversation()
    elif choice == "6":
        kind = _ask("1) Pasta registrada  2) Documento: ")
        if kind == "1":
            target = _choose_folder()
        elif kind == "2":
            target = _ask("Caminho do documento: ")
            if not target:
                print(CANCELLED)
        else:
            print(CANCELLED)
            target = None
        if target:
            run(cli.cmd_delete, alvo=target)
    elif choice == "7":
        run(cli.cmd_check)
    else:
        print("Opção inválida.")


def run_menu() -> int:
    while True:
        print(MENU)
        try:
            choice = _ask("Opção: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice == "0":
            return 0
        try:
            _action(choice)
        except (EOFError, KeyboardInterrupt):
            print()
        print()
