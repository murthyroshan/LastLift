"""End-to-end answer times for the agent, measured from outside against a deployed API.

    python scripts/latency.py --prod            # https://lastlift-api.onrender.com, the ten questions below
    python scripts/latency.py --base http://localhost:8000

Each question goes to POST /api/ask; the time is the agent's own `done` event (question in, grounded answer out:
tool calls over MCP, the language model, the grounding check), plus the wall-clock time of the request. The
first request also warms a sleeping free instance, so it is sent once before timing starts.
"""
import argparse
import statistics
import time

import httpx

PROD = "https://lastlift-api.onrender.com"
QUESTIONS = [
    "Is Chinatown step-free right now?",
    "What happens if lift 813 fails too?",
    "Can I get step-free onto the Wonderland-bound platform at Revere Beach right now?",
    "Which lifts should be repaired or protected first?",
    "What changed at Alewife now that lift 961 is closed?",
    "Elevator 782 at Worcester is out. Who is affected?",
    "Is Downtown Crossing step-free if lift 891 breaks?",
    "Which lifts are out of service right now?",
    "How fragile is Kendall/MIT for wheelchair users?",
    "I need to get from South Station to Alewife step-free today. Which lifts does that depend on?",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", action="store_true")
    ap.add_argument("--base", default=PROD)
    a = ap.parse_args()
    base = PROD if a.prod else a.base
    with httpx.Client(timeout=180) as c:
        c.get(f"{base}/healthz")                                   # wake the instance; not timed
        rows = []
        for q in QUESTIONS:
            t0 = time.perf_counter()
            r = c.post(f"{base}/api/ask", json={"question": q, "scope": "demo"}).json()
            wall = (time.perf_counter() - t0) * 1000
            done = next((e for e in r.get("events", []) if e.get("type") == "done"), {})
            fails = sum(1 for e in r.get("events", []) if e.get("stage") == "llm_failover")
            rows.append({"q": q, "agent_ms": done.get("ms", wall), "wall_ms": wall, "source": r.get("source"), "failovers": fails})
            print(f"{done.get('ms', wall) / 1000:6.1f} s  agent  {wall / 1000:6.1f} s  wall  {r.get('source'):8s}  {q[:60]}")
    ag = sorted(r["agent_ms"] for r in rows)
    p95 = ag[min(len(ag) - 1, round(0.95 * (len(ag) - 1)))]
    llm = sum(1 for r in rows if r["source"] == "llm")
    print(f"\nmedian {statistics.median(ag) / 1000:.1f} s, p95 {p95 / 1000:.1f} s over {len(rows)} questions; "
          f"{llm}/{len(rows)} answered by the language model (the rest by the grounded template); "
          f"{sum(r['failovers'] for r in rows)} model failovers")


if __name__ == "__main__":
    main()
