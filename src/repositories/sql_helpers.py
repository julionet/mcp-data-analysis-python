"""Auxiliares de SQL compartilhados pelos repositórios administrativos — F23 §4.3."""


def like_pattern(term: str | None) -> str | None:
    """Padrão ILIKE de substring, com `\\`, `%` e `_` do termo escapados (use ESCAPE '\\')."""
    if term is None or term == "":
        return None
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def set_clause(fields: dict, first_index: int = 1) -> str:
    """`col = $n, ...` na ordem do dict (os valores são ligados na mesma ordem).
    As chaves são nomes de coluna fixos do código, nunca entrada do usuário."""
    return ", ".join(f"{col} = ${i}" for i, col in enumerate(fields, start=first_index))
