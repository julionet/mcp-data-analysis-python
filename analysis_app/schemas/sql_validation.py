"""Validação do SQL de analysis_steps — o servidor só executa consultas (SELECT).

O engine embrulha o SQL em `SELECT COUNT(*) FROM (<sql>) sub` (Volume Guard) e
o entrega a `adapter.execute_query()`, que roda em um pool com autocommit — um
INSERT/UPDATE/DELETE cadastrado por engano seria executado de verdade.
Esta validação recusa isso antes de tocar o data source.

Não é uma fronteira de segurança: quem consegue gravar em `analysis_steps`
já controla o SQL. A proteção real contra escrita é o usuário do data source
ter permissão somente de leitura (ARQUITETURA.md §8.2). Aqui é uma rede de
segurança contra erro de cadastro.
"""

import re

from schemas.exceptions import InvalidAnalysisSchemaError

# Literais e identificadores entre aspas, e comentários, são removidos antes da
# checagem de palavras — assim `'delete'` ou `"update"` não geram falso positivo.
# Limitação conhecida: dollar-quoting do PostgreSQL ($$...$$) não é tratado.
_STRIP_PATTERN = re.compile(
    r"""
    --[^\n]*            # comentário de linha
    | /\*.*?\*/         # comentário de bloco
    | '(?:[^']|'')*'    # literal string
    | "(?:[^"]|"")*"    # identificador entre aspas (ANSI/PostgreSQL)
    | `[^`]*`           # identificador entre crases (MySQL)
    | (?<!:):[A-Za-z_][A-Za-z0-9_]*   # placeholder :param (não confundir com cast ::tipo)
    """,
    re.VERBOSE | re.DOTALL,
)

_FORBIDDEN_KEYWORDS = frozenset(
    {
        "INSERT", "UPDATE", "DELETE", "MERGE",  # REPLACE fica de fora: é função de string comum
        "DROP", "ALTER", "CREATE", "TRUNCATE", "RENAME",
        "GRANT", "REVOKE",
        "CALL", "EXEC", "EXECUTE",
        "INTO",  # SELECT ... INTO cria tabela/arquivo
    }
)  # fmt: skip

_WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def validate_select_only(sql: str) -> None:
    """Levanta InvalidAnalysisSchemaError se `sql` não for uma única consulta SELECT."""
    cleaned = _STRIP_PATTERN.sub(" ", sql).strip()
    words = _WORD_PATTERN.findall(cleaned.upper())

    if not words or words[0] != "SELECT":
        raise InvalidAnalysisSchemaError(
            "SQL da análise não permitido: só consultas SELECT são aceitas."
        )
    if ";" in cleaned:
        raise InvalidAnalysisSchemaError(
            "SQL da análise não permitido: ';' não é aceito (uma única consulta, sem terminador)."
        )
    forbidden = sorted(_FORBIDDEN_KEYWORDS.intersection(words))
    if forbidden:
        raise InvalidAnalysisSchemaError(
            f"SQL da análise não permitido: palavra(s) proibida(s) {', '.join(forbidden)} — só SELECT é aceito."
        )
