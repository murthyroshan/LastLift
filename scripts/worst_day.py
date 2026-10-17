"""The worst day: for B = 1..10 lift failures, the set that leaves the most platform-directions without a step-free
route (a resilience stress test; the answer is what to protect first).

    python scripts/worst_day.py      # writes data/worst_day.json and claims (worst_*)

Method (exact under one cap, stated): a platform-direction has no step-free route exactly when the failed lifts
contain one of its minimal failure sets (M10, network.json). Effects never cross complexes, so for each complex the
best value with b failures (b <= 3) is found by enumerating every subset of its relevant lifts, and a knapsack over
complexes combines them for every budget B. Values count platform-directions; scheduled departures at those
platforms are reported next to them. For B <= 3 a brute force over every subset of every relevant lift in the
network checks the optimum; for B > 3 the result is optimal under the cap of 3 failures per complex.
"""
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift.seed import latest_snapshot  # noqa: E402

B_MAX, PER_CX = 10, 3


def load():
    snap = latest_snapshot()
    net = json.loads((snap / "network.json").read_text(encoding="utf-8"))
    deps = {}
    for line in (snap / "nodes.jsonl").read_text(encoding="utf-8").splitlines():
        n = json.loads(line)
        if "Platform" in n["labels"] and "Node" in n["labels"]:
            deps[n["stop_id"]] = max(deps.get(n["stop_id"], 0), n.get("deps_day") or 0)
    dirs = []                                     # (cx, stop, dir, [minimal sets as frozensets], deps)
    for stop, p in net["platform"].items():
        for d in ("board", "exit"):
            m = p[d].get("minimal")
            if m:
                dirs.append((p["cx"], stop, d, [frozenset(x) for x in m], deps.get(stop, 0)))
    return net, dirs


def lost(dirs, failed: frozenset):
    return [x for x in dirs if any(s <= failed for s in x[3])]


def per_complex(dirs):
    by_cx = defaultdict(list)
    for x in dirs:
        by_cx[x[0]].append(x)
    table = {}
    for cx, ds in by_cx.items():
        lifts = sorted(set().union(*(s for x in ds for s in x[3])))
        best = {0: (0, 0, ())}
        for b in range(1, PER_CX + 1):
            top = best[b - 1]
            for S in itertools.combinations(lifts, b):
                hit = lost(ds, frozenset(S))
                val = (len(hit), sum(x[4] for x in hit))
                if val > top[:2]:
                    top = (*val, S)
            best[b] = top
        table[cx] = best
    return table


def knapsack(table):
    """best[B] = (platform-directions, departures, allocation) maximised over complexes."""
    best = {0: (0, 0, ())}
    for B in range(1, B_MAX + 1):
        best[B] = best[B - 1]
    cur = {B: (0, 0, ()) for B in range(B_MAX + 1)}
    for cx, f in sorted(table.items()):
        nxt = dict(cur)
        for B in range(B_MAX + 1):
            for b in range(1, min(PER_CX, B) + 1):
                prev = cur[B - b]
                cand = (prev[0] + f[b][0], prev[1] + f[b][1], prev[2] + tuple((cx, x) for x in f[b][2]))
                if cand[:2] > nxt[B][:2]:
                    nxt[B] = cand
        cur = nxt
    return cur


def brute(dirs, B):
    lifts = sorted(set().union(*(s for x in dirs for s in x[3])))
    by_lift = defaultdict(list)
    for x in dirs:
        for f in set().union(*x[3]):
            by_lift[f].append(x)
    top = (0, 0)
    for S in itertools.combinations(lifts, B):
        fs = frozenset(S)
        cand = {id(x): x for f in S for x in by_lift[f]}.values()
        hit = [x for x in cand if any(s <= fs for s in x[3])]
        top = max(top, (len(hit), sum(x[4] for x in hit)))
    return top


def main():
    net, dirs = load()
    table = per_complex(dirs)
    best = knapsack(table)
    st = {f: x["station_id"] for f, x in net["lifts"].items()}
    names = net["names"]
    rows = []
    for B in range(1, B_MAX + 1):
        n, w, alloc = best[B]
        lifts = sorted({f for _, f in alloc})
        hit = lost(dirs, frozenset(lifts))
        rows.append({"B": B, "platform_directions": n, "departures": w, "used": len(lifts),
                     "lifts": [{"facility_id": f, "station_id": st.get(f, ""), "station": names.get(st.get(f, ""), "")}
                               for f in lifts],
                     "lost": [f"{x[1]}:{x[2]}" for x in sorted(hit, key=lambda x: (x[1], x[2]))]})
    checks = {}
    for B in (1, 2, 3):
        bf = brute(dirs, B)
        checks[str(B)] = {"brute_force": list(bf), "dp": [best[B][0], best[B][1]], "equal": list(bf) == [best[B][0], best[B][1]]}
    monotone = all(rows[i]["platform_directions"] <= rows[i + 1]["platform_directions"] for i in range(len(rows) - 1))
    doc = {"rows": rows, "checks": checks, "monotone": monotone, "per_complex_cap": PER_CX,
           "assessed_platform_directions": len(dirs)}
    (ROOT / "data" / "worst_day.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8",
                                                  newline="\n")
    claims_path = ROOT / "claims.json"
    claims = {k: v for k, v in json.loads(claims_path.read_text(encoding="utf-8")).items() if not k.startswith("worst_")}
    claims.update({"worst_b1": rows[0]["platform_directions"], "worst_b3": rows[2]["platform_directions"],
                   "worst_b5": rows[4]["platform_directions"], "worst_b10": rows[9]["platform_directions"],
                   "worst_bruteforce_equal": all(c["equal"] for c in checks.values())})
    claims_path.write_text(json.dumps(claims, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    for r in rows:
        print(r["B"], r["platform_directions"], r["departures"], [x["facility_id"] for x in r["lifts"]])
    print("checks", checks, "monotone", monotone)
    return 0


if __name__ == "__main__":
    sys.exit(main())
