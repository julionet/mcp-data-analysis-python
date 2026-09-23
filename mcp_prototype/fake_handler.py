"""Handler fake — substitui HandlerRegistry/DataHandler do F3 (ARQUITETURA.md §4.3)."""


def apply(rows: list[dict]) -> list[dict]:
    """Ordena por vendas desc e marca a maior região com destaque."""
    ordered = sorted((dict(r) for r in rows), key=lambda r: r["vendas"], reverse=True)
    if ordered:
        ordered[0]["destaque"] = True
    return ordered
