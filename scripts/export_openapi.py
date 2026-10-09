"""Gera docs/openapi.json a partir do app (F16 §4.6) — sem conectar em nenhum banco.

Uso (na raiz do repositório, com o .venv):
    .venv/bin/python scripts/export_openapi.py            # grava docs/openapi.json
    .venv/bin/python scripts/export_openapi.py --check    # sai com 1 se o arquivo versionado estiver desatualizado

A conexão com o Config DB só acontece no lifespan do app, então importar `main` e chamar
`app.openapi()` não precisa de banco. As variáveis obrigatórias do `Settings` recebem valores
fictícios só se não estiverem definidas (o conteúdo do OpenAPI não depende delas). A saída é
determinística (chaves ordenadas), para o diff do git ser estável.
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "openapi.json"


def build_openapi_text() -> str:
    from cryptography.fernet import Fernet

    os.environ.setdefault("POSTGRES_CONFIG_HOST", "localhost")
    os.environ.setdefault("POSTGRES_CONFIG_USER", "openapi")
    os.environ.setdefault("POSTGRES_CONFIG_PASSWORD", "openapi")
    os.environ.setdefault("POSTGRES_CONFIG_DATABASE", "openapi")
    os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
    sys.path.insert(0, str(ROOT / "src"))

    from main import app

    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="não grava; falha se docs/openapi.json estiver desatualizado")
    args = parser.parse_args()

    text = build_openapi_text()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
        if current != text:
            print(
                "docs/openapi.json desatualizado. Regenere com: "
                ".venv/bin/python scripts/export_openapi.py",
                file=sys.stderr,
            )
            return 1
        print("docs/openapi.json em sincronia.")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"Gravado {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
