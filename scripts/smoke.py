"""Production smoke test: the deployed API does what the README says, from the outside.

    python scripts/smoke.py --prod                         # https://lastlift-api.onrender.com
    python scripts/smoke.py --base http://localhost:8000   # a local server
    python scripts/smoke.py --prod --origin https://<site>  # also check CORS for the website's origin

Checks: /healthz (and how long a cold start took), /v1/health reports FalkorDB 4.22, a golden tool call
(resolve_place Alewife -> place-alfcl), a what-if, the agent (/api/ask), MCP tools/list over HTTP, the Cypher
catalogue, and CORS for the website origin. Exits non-zero on any failure.
"""
import argparse
import json
import sys
import time

import httpx

PROD = "https://lastlift-api.onrender.com"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", action="store_true")
    ap.add_argument("--base", default=None)
    ap.add_argument("--origin", default=None, help="website origin to check CORS for")
    ap.add_argument("--wake-timeout", type=int, default=180)
    a = ap.parse_args(argv)
    base = (a.base or (PROD if a.prod else "http://localhost:8000")).rstrip("/")
    results, c = [], httpx.Client(timeout=60)

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"[{'ok' if ok else 'FAIL'}] {name}{': ' + detail if detail else ''}", flush=True)

    t0 = time.perf_counter()
    while True:                                   # a free host sleeps when idle: time the wake-up
        try:
            r = c.get(f"{base}/healthz")
            if r.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if time.perf_counter() - t0 > a.wake_timeout:
            check("healthz", False, f"no 200 within {a.wake_timeout} s")
            return 1
        time.sleep(3)
    check("healthz", True, f"200 after {time.perf_counter() - t0:.1f} s (includes any cold start)")

    h = c.get(f"{base}/v1/health").json()
    check("FalkorDB 4.22 behind the API", str((h.get("falkordb") or {}).get("module_version", "")).startswith("4.22"),
          json.dumps(h.get("falkordb")))

    r = c.post(f"{base}/v1/tools/resolve_place", json={"query": "Alewife"}).json()
    ids = [s["station_id"] for s in (r.get("data") or {}).get("stations", [])]
    check("golden tool call resolve_place('Alewife')", "place-alfcl" in ids, r.get("summary", ""))

    r = c.post(f"{base}/v1/tools/platform_redundancy", json={"station_id": "place-alfcl"}).json()
    check("platform_redundancy(Alewife) names lift 813", "813" in r.get("summary", ""), r.get("summary", "")[:120])

    r = c.post(f"{base}/v1/tools/what_if_close", json={"facility_ids": ["813"]}, timeout=120).json()
    check("what_if_close(813) cuts Alewife platforms", r.get("ok") and len((r.get("data") or {}).get("newly_lost", [])) >= 1,
          r.get("summary", "")[:120])

    r = c.post(f"{base}/api/ask", json={"question": "Is Chinatown step-free right now?"}, timeout=120).json()
    check("agent /api/ask answers from the graph", "Chinatown" in r.get("answer", ""),
          f"source={r.get('source')}: {r.get('answer', '')[:100]}")

    r = c.post(f"{base}/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
               headers={"Accept": "application/json, text/event-stream"})
    check("MCP tools/list over streamable HTTP", r.status_code == 200 and "step_free_route" in r.text)

    q = c.get(f"{base}/v1/queries").json()
    check("Cypher catalogue", "Q_MAXFLOW" in q and "algo.maxFlow" in q["Q_MAXFLOW"], f"{len(q)} statements")

    if a.origin:
        r = c.options(f"{base}/v1/tools/resolve_place", headers={
            "Origin": a.origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
        check(f"CORS allows {a.origin}", r.headers.get("access-control-allow-origin") == a.origin,
              r.headers.get("access-control-allow-origin", "(none)"))

    print(f"{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
