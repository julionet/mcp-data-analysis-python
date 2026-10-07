"""F15 §6.1 — só parsing de argumentos e cálculo de percentis dos scripts de performance
(o tempo medido é instável e não é testado)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import benchmark  # noqa: E402
import load_test  # noqa: E402
from perf_stats import percentile, summarize  # noqa: E402


class TestPercentile:
    def test_nearest_rank(self):
        values = list(range(1, 101))  # 1..100
        assert percentile(values, 50) == 50
        assert percentile(values, 95) == 95
        assert percentile(values, 100) == 100

    def test_nao_exige_ordenado_e_aceita_um_valor(self):
        assert percentile([30, 10, 20], 50) == 20
        assert percentile([7], 95) == 7

    def test_vazio_ou_pct_invalido_falha(self):
        with pytest.raises(ValueError):
            percentile([], 50)
        with pytest.raises(ValueError):
            percentile([1], 101)

    def test_summarize(self):
        assert summarize([10, 20, 30, 40]) == {"n": 4, "p50": 20, "p95": 40, "max": 40}


class TestBenchmarkArgs:
    def test_defaults(self):
        a = benchmark.build_parser().parse_args([])
        assert a.iterations == 30 and a.compare is None and a.explain is False

    def test_flags(self):
        a = benchmark.build_parser().parse_args(
            ["--iterations", "5", "--compare", "b.json", "--explain", "--hit-analysis", "x"]
        )
        assert (a.iterations, a.compare, a.explain, a.hit_analysis) == (5, "b.json", True, "x")

    def test_tabela_mostra_variacao_contra_baseline(self):
        cur = {"n": 5, "p50": 4.0, "p95": 5.0, "max": 6.0}
        line = benchmark._fmt_row("cache_hit", cur, {"n": 5, "p50": 9.0, "p95": 10.0, "max": 11.0})
        assert "OK" in line and "-50.0%" in line

    def test_meta_estourada_marca_falhou(self):
        cur = {"n": 5, "p50": 90.0, "p95": 150.0, "max": 200.0}
        assert "FALHOU" in benchmark._fmt_row("cache_hit", cur, None)


class TestLoadTestArgs:
    def test_defaults(self):
        a = load_test.build_parser().parse_args([])
        assert a.clients == 10 and a.duration == 60 and a.insecure is False

    def test_flags(self):
        a = load_test.build_parser().parse_args(
            ["--clients", "20", "--duration", "5", "--analyses", "a", "b", "--insecure", "--db-check"]
        )
        assert (a.clients, a.duration, a.analyses, a.insecure, a.db_check) == (20, 5, ["a", "b"], True, True)


class TestParseResponse:
    PAYLOAD = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    def test_json_puro(self):
        assert load_test.parse_response("application/json", json.dumps(self.PAYLOAD)) == self.PAYLOAD

    def test_sse(self):
        body = f"event: message\ndata: {json.dumps(self.PAYLOAD)}\n\n"
        assert load_test.parse_response("text/event-stream", body) == self.PAYLOAD
