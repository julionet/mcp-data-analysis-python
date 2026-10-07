"""Estatísticas compartilhadas por benchmark.py e load_test.py (F15 §4.4/§4.6)."""

import math


def percentile(values: list[float], pct: float) -> float:
    """Percentil por ranking mais próximo (nearest-rank). `values` não precisa estar ordenado."""
    if not values:
        raise ValueError("percentile() exige ao menos um valor")
    if not 0 <= pct <= 100:
        raise ValueError("pct deve estar entre 0 e 100")
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize(values_ms: list[float]) -> dict:
    """p50/p95/máx (ms) e nº de amostras."""
    return {
        "n": len(values_ms),
        "p50": round(percentile(values_ms, 50), 2),
        "p95": round(percentile(values_ms, 95), 2),
        "max": round(max(values_ms), 2),
    }
