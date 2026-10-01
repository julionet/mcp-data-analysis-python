def min_max_normalize(results: list[dict]) -> list[dict]:
    """Reescala 'score' de uma lista de resultados para [0, 1]."""
    if not results:
        return results
    scores = [r["score"] for r in results]
    lo, hi = min(scores), max(scores)
    span = hi - lo
    for r in results:
        r["score_norm"] = (r["score"] - lo) / span if span > 0 else 1.0
    return results


def weighted_fusion(
    semantic_results: list[dict],
    lexical_results: list[dict],
    alpha: float = 0.5,
    k: int = 5,
) -> list[dict]:
    """Combina os dois rankings por média ponderada dos scores normalizados."""
    semantic_results = min_max_normalize(list(semantic_results))
    lexical_results = min_max_normalize(list(lexical_results))

    combined: dict[int, dict] = {}
    for r in semantic_results:
        combined[r["index"]] = {
            "index": r["index"],
            "text": r["text"],
            "semantic_score": r["score_norm"],
            "lexical_score": 0.0,
        }
    for r in lexical_results:
        entry = combined.setdefault(
            r["index"],
            {"index": r["index"], "text": r["text"], "semantic_score": 0.0, "lexical_score": 0.0},
        )
        entry["lexical_score"] = r["score_norm"]

    for entry in combined.values():
        entry["score"] = alpha * entry["semantic_score"] + (1 - alpha) * entry["lexical_score"]

    ranked = sorted(combined.values(), key=lambda e: e["score"], reverse=True)
    return ranked[:k]


def reciprocal_rank_fusion(
    semantic_results: list[dict],
    lexical_results: list[dict],
    k: int = 5,
    rrf_k: int = 60,
) -> list[dict]:
    """Combina os dois rankings por posição (rank), não por valor de score."""
    combined: dict[int, dict] = {}

    for rank, r in enumerate(semantic_results, start=1):
        entry = combined.setdefault(
            r["index"], {"index": r["index"], "text": r["text"], "score": 0.0}
        )
        entry["score"] += 1 / (rrf_k + rank)

    for rank, r in enumerate(lexical_results, start=1):
        entry = combined.setdefault(
            r["index"], {"index": r["index"], "text": r["text"], "score": 0.0}
        )
        entry["score"] += 1 / (rrf_k + rank)

    ranked = sorted(combined.values(), key=lambda e: e["score"], reverse=True)
    return ranked[:k]
