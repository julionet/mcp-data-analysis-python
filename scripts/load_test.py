"""Teste de carga do /mcp (F15 §4.6) — N clientes simultâneos contra o servidor em execução.

Uso (servidor no ar, ex.: docker compose local ou `python src/run_https.py`):
    python scripts/load_test.py --clients 10 --duration 60 --token-file secrets/admin-token.txt
    python scripts/load_test.py --url https://localhost:3000/mcp --insecure --params '{"x": 1}'

Cada cliente faz, em loop, `tools/call` de uma análise liberada (alternando as passadas por
`--analyses`; sem a flag, usa as `tools/list` do token). O servidor é stateless: cada POST é
um JSON-RPC independente, sem `initialize`.

Ao final: contagem de respostas por status, erros, p50/p95/máx e — com `--db-check` — confere que
TODA execução que chegou ao AnalysisService foi gravada em execution_history (RNF4), lendo o
Config DB com as credenciais do .env.
"""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from perf_stats import summarize  # noqa: E402

# Respostas que o servidor devolve ANTES de gravar execution_history (análise inexistente/vedada
# e a validação de call_tool): não entram na conta de "toda execução gravada".
_NOT_LOGGED_CODES = {"ANALYSIS_NOT_FOUND"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Teste de carga do /mcp (F15).")
    p.add_argument("--url", default="https://localhost:3000/mcp")
    p.add_argument("--clients", type=int, default=10, help="clientes simultâneos (padrão 10)")
    p.add_argument("--duration", type=float, default=60, help="segundos de carga (padrão 60)")
    p.add_argument("--token-file", default="secrets/admin-token.txt")
    p.add_argument("--analyses", nargs="*", help="nomes das análises (sem o prefixo execute_)")
    p.add_argument("--params", default="{}", help="JSON com os argumentos de cada chamada")
    p.add_argument("--insecure", action="store_true", help="não valida o certificado TLS (mkcert/dev)")
    p.add_argument("--db-check", action="store_true", help="confere execution_history no Config DB (.env)")
    return p


def parse_response(content_type: str, body: str) -> dict:
    """Resposta do /mcp: JSON puro ou SSE (`data: {...}`). Devolve o objeto JSON-RPC."""
    if "text/event-stream" in content_type:
        for line in body.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise ValueError("SSE sem linha data:")
    return json.loads(body)


class Counters:
    def __init__(self) -> None:
        self.latencies_ms: list[float] = []
        self.statuses: Counter = Counter()
        self.errors: Counter = Counter()
        self.expected_logged = 0


async def _rpc(client, url: str, headers: dict, method: str, params: dict, req_id: int) -> dict:
    resp = await client.post(
        url, headers=headers, json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
    )
    resp.raise_for_status()
    return parse_response(resp.headers.get("content-type", ""), resp.text)


async def _worker(idx: int, client, args, headers: dict, tools: list[str], arguments: dict,
                  deadline: float, c: Counters) -> None:
    n = 0
    while time.monotonic() < deadline:
        tool = tools[(idx + n) % len(tools)]
        n += 1
        start = time.perf_counter()
        try:
            msg = await _rpc(client, args.url, headers, "tools/call",
                             {"name": tool, "arguments": arguments}, idx * 1_000_000 + n)
            elapsed = (time.perf_counter() - start) * 1000
            if "error" in msg:
                c.errors[f"jsonrpc:{msg['error'].get('code')}"] += 1
                continue
            result = json.loads(msg["result"]["content"][0]["text"])
            c.latencies_ms.append(elapsed)
            status = result.get("status")
            c.statuses[status] += 1
            if status == "error" and result.get("error_code") in _NOT_LOGGED_CODES:
                continue
            c.expected_logged += 1
        except Exception as exc:  # erro de transporte/HTTP conta como erro, não derruba o teste
            c.errors[type(exc).__name__] += 1


async def _db_count(since: datetime) -> int:
    from database.connection import connect_config_db, config_db_adapter, disconnect_config_db

    await connect_config_db()
    try:
        # executed_at é TIMESTAMP sem fuso (NOW() do servidor do BD) — comparar em relógio do BD
        return await config_db_adapter.execute_query(
            "SELECT COUNT(*) FROM execution_history WHERE executed_at >= $1", {"since": since}, scalar=True)
    finally:
        await disconnect_config_db()


async def _run(args) -> int:
    import httpx

    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    arguments = json.loads(args.params)
    limits = httpx.Limits(max_connections=args.clients * 2)
    async with httpx.AsyncClient(verify=not args.insecure, timeout=60, limits=limits) as client:
        if args.analyses:
            tools = [f"execute_{a}" for a in args.analyses]
        else:
            listed = await _rpc(client, args.url, headers, "tools/list", {}, 0)
            tools = [t["name"] for t in listed["result"]["tools"]]
        if not tools:
            print("Nenhuma análise liberada para o token.")
            return 2
        print(f"{args.clients} clientes x {args.duration:.0f}s | análises: {', '.join(tools)}")

        c = Counters()
        db_since = None
        if args.db_check:
            # relógio do BD != relógio local: usa o do Postgres para o corte
            from database.connection import connect_config_db, config_db_adapter, disconnect_config_db
            await connect_config_db()
            db_since = await config_db_adapter.execute_query("SELECT NOW()::timestamp AS t")
            db_since = db_since[0]["t"]
            await disconnect_config_db()

        deadline = time.monotonic() + args.duration
        await asyncio.gather(*(
            _worker(i, client, args, headers, tools, arguments, deadline, c) for i in range(args.clients)
        ))

    total = sum(c.statuses.values()) + sum(c.errors.values())
    print(f"\nRequisições: {total} | com resposta: {len(c.latencies_ms)} | "
          f"throughput ~ {len(c.latencies_ms) / args.duration:.1f} req/s")
    print(f"Status das análises: {dict(c.statuses)}")
    print(f"Erros de transporte/JSON-RPC: {dict(c.errors) or 0}")
    if c.latencies_ms:
        s = summarize(c.latencies_ms)
        print(f"Latência ms: p50={s['p50']} p95={s['p95']} máx={s['max']}")

    ok = not c.errors
    if args.db_check:
        logged = await _db_count(db_since)
        print(f"execution_history: esperado >= {c.expected_logged}, gravado {logged}")
        # `logged` pode exceder o esperado só por execuções de outros clientes na mesma janela
        if logged < c.expected_logged:
            print("FALHOU: há execuções sem registro em execution_history (RNF4)")
            ok = False
    print("RESULTADO:", "OK" if ok else "FALHOU")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
