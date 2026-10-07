"""Benchmark das metas de RNF1 (F15 §4.4) — roda em processo, contra o Config DB do .env.

Uso (na raiz do repositório, com o postgres do compose no ar e o admin criado):
    python scripts/benchmark.py --token-file secrets/admin-token.txt --output baseline.json
    # ... muda algo ...
    python scripts/benchmark.py --token-file secrets/admin-token.txt --compare baseline.json
    python scripts/benchmark.py --token-file secrets/admin-token.txt --explain

Metas: cache hit < 100 ms, COUNT(*) < 500 ms, list_tools < 2 s, análise leve < 5 s.
`auth` não tem meta (referência: 3 idas ao Config DB).

Análises usadas (escolhidas entre as liberadas ao usuário do token, ou via flags):
  --hit-analysis   cache_frequency != 'none' (executada 1x para aquecer, depois medida)
  --miss-analysis  cache_frequency == 'none' (todas as execuções vão ao data source)
Parâmetros: --params '{"x": 1}' (JSON, vale para as análises escolhidas).
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from perf_stats import summarize  # noqa: E402

# nome da medição -> meta em ms (None = só referência)
TARGETS_MS = {
    "cache_hit": 100,
    "count": 500,
    "list_tools": 2000,
    "light_analysis": 5000,
    "auth": None,
}

# queries de permissão/lookup (F15 §4.4); $1 = user_id
_EXPLAIN_QUERIES = {
    "get_allowed_for_user / get_allowed_analysis_ids": (
        "SELECT DISTINCT a.id FROM analyses a "
        "JOIN profile_analyses pa ON pa.analysis_id = a.id "
        "JOIN user_profiles up ON up.profile_id = pa.profile_id "
        "JOIN profiles p ON p.id = pa.profile_id "
        "WHERE up.user_id = $1 AND a.is_active = true AND p.is_active = true"
    ),
    "analyses.get_by_name": "SELECT id FROM analyses WHERE name = (SELECT name FROM analyses LIMIT 1)",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Benchmark das metas de RNF1 (F15).")
    p.add_argument("--token-file", default="secrets/admin-token.txt", help="arquivo com o token Bearer")
    p.add_argument("--iterations", type=int, default=30, help="repetições por medição (padrão 30)")
    p.add_argument("--params", default="{}", help="JSON com os parâmetros das análises medidas")
    p.add_argument("--hit-analysis", help="nome da análise para cache hit (padrão: 1ª com cache)")
    p.add_argument("--miss-analysis", help="nome da análise sem cache (padrão: 1ª com cache_frequency='none')")
    p.add_argument("--output", help="grava o resultado neste JSON (padrão: benchmark-<data>.json)")
    p.add_argument("--compare", help="JSON de baseline para mostrar a variação")
    p.add_argument("--explain", action="store_true", help="roda EXPLAIN (ANALYZE, BUFFERS) das queries de permissão")
    return p


async def _time_ms(fn, iterations: int) -> list[float]:
    samples = []
    for _ in range(iterations):
        start = time.perf_counter()
        await fn()
        samples.append((time.perf_counter() - start) * 1000)
    return samples


async def _run(args) -> dict:
    from database.connection import config_db_adapter, connect_config_db, disconnect_config_db
    from mcp_transport import tools
    from schemas.analysis_parameters import to_pydantic_model
    from schemas.exceptions import VolumeExceededError

    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    params = json.loads(args.params)
    await connect_config_db()
    results: dict[str, dict] = {}
    try:
        user = await tools.auth_service.authenticate(token)
        allowed = await tools.analysis_service.get_allowed_analyses(user.id)
        by_name = {a.name: a for a in allowed}

        def pick(name, want_none):
            if name:
                return by_name[name]
            return next((a for a in allowed if (a.cache_frequency == "none") == want_none), None)

        hit_a, miss_a = pick(args.hit_analysis, False), pick(args.miss_analysis, True)
        print(f"Usuário: {user.name} | análises liberadas: {len(allowed)} | "
              f"hit={hit_a.name if hit_a else '-'} | miss={miss_a.name if miss_a else '-'}")

        n = args.iterations
        results["auth"] = summarize(await _time_ms(lambda: tools.auth_service.authenticate(token), n))

        async def list_tools():
            u = await tools.auth_service.authenticate(token)
            await tools.list_tools(u)

        results["list_tools"] = summarize(await _time_ms(list_tools, n))

        if hit_a:
            call = lambda: tools.call_tool(f"execute_{hit_a.name}", dict(params), user)  # noqa: E731
            first = await call()  # aquece o cache
            if first.get("status") != "success":
                print(f"  ! {hit_a.name}: {first.get('status')} {first.get('mensagem', '')}")
            results["cache_hit"] = summarize(await _time_ms(call, n))

        if miss_a:
            call = lambda: tools.call_tool(f"execute_{miss_a.name}", dict(params), user)  # noqa: E731
            first = await call()
            if first.get("status") != "success":
                print(f"  ! {miss_a.name}: {first.get('status')} {first.get('mensagem', '')}")
            results["light_analysis"] = summarize(await _time_ms(call, n))

            # COUNT(*) isolado: mesma montagem de AnalysisService._run_query
            svc = tools.analysis_service
            ds = await svc.data_source_repo.get_by_id(miss_a.data_source_id)
            step = (await svc.analysis_repo.get_steps(miss_a.id))[0]
            adapter = await svc._get_adapter(ds)
            sql = adapter.translate_params(step.definition["sql"], step.definition["params"])
            count_sql = f"SELECT COUNT(*) FROM ({sql}) sub"
            values = to_pydantic_model(miss_a.parameters)(**params).model_dump()  # como o serviço
            ordered = {k: values[k] for k in step.definition["params"]}

            async def count():
                try:
                    await svc.volume_guard.check_row_count(adapter, count_sql, ordered)
                except VolumeExceededError:
                    pass  # recusa também é uma execução completa do COUNT(*)

            results["count"] = summarize(await _time_ms(count, n))

        if args.explain:
            for label, sql in _EXPLAIN_QUERIES.items():
                rows = await config_db_adapter.execute_query(
                    f"EXPLAIN (ANALYZE, BUFFERS) {sql}", {"u": user.id} if "$1" in sql else None)
                print(f"\n== EXPLAIN: {label}")
                for r in rows:
                    print("  " + r["QUERY PLAN"])
    finally:
        await tools.analysis_service.aclose()
        await disconnect_config_db()
    return results


def _fmt_row(name: str, cur: dict, base: dict | None) -> str:
    target = TARGETS_MS[name]
    ok = "-" if target is None else ("OK" if cur["p95"] < target else "FALHOU")
    line = f"{name:<16}{cur['n']:>4}{cur['p50']:>10.2f}{cur['p95']:>10.2f}{cur['max']:>10.2f}  " \
           f"{'-' if target is None else target:>6}  {ok:<6}"
    if base:
        delta = (cur["p95"] - base["p95"]) / base["p95"] * 100 if base["p95"] else 0.0
        line += f"  p95 vs baseline: {base['p95']:.2f} -> {cur['p95']:.2f} ({delta:+.1f}%)"
    return line


def print_table(results: dict, baseline: dict | None) -> None:
    print(f"\n{'medição':<16}{'n':>4}{'p50 ms':>10}{'p95 ms':>10}{'máx ms':>10}  {'meta':>6}  {'p95':<6}")
    for name in TARGETS_MS:
        if name in results:
            print(_fmt_row(name, results[name], (baseline or {}).get(name)))


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # asyncpg no Proactor
    results = asyncio.run(_run(args))
    baseline = json.loads(Path(args.compare).read_text(encoding="utf-8"))["results"] if args.compare else None
    print_table(results, baseline)
    out = Path(args.output or f"benchmark-{date.today().isoformat()}.json")
    out.write_text(json.dumps({"date": date.today().isoformat(), "iterations": args.iterations,
                               "results": results}, indent=2), encoding="utf-8")
    print(f"\nResultado gravado em {out}")


if __name__ == "__main__":
    main()
