import argparse
import sys

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.cli", description="RAG Training — CLI")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init-db", help="aplica o esquema do banco (idempotente)")
    sub.add_parser("check", help="verifica configuração e banco")

    args = parser.parse_args(argv)
    commands = {"init-db": cmd_init_db, "check": cmd_check}
    if args.command is None:
        parser.print_help()
        return 0
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
