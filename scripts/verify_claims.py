"""Independently re-derive LastLift's numbers from the committed snapshot files (no FalkorDB).

    python scripts/verify_claims.py

1. Rebuilds the step-free network from data/snapshots/<date>/{nodes,edges}.jsonl,
2. recomputes board/exit k for every platform with NetworkX,
3. compares them with precomputed.jsonl (the FalkorDB sweep) and re-derives every core key of
   claims.json from scratch. Exits non-zero on any mismatch.
"""
import collections
import json
import sys
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
SNAP = sorted(p for p in (ROOT / "data" / "snapshots").iterdir() if (p / "MANIFEST.json").is_file())[-1]


def main():
    manifest = json.loads((SNAP / "MANIFEST.json").read_text(encoding="utf-8"))
    big = manifest["big"]
    nodes = [json.loads(l) for l in (SNAP / "nodes.jsonl").read_text(encoding="utf-8").splitlines()]
    edges = [json.loads(l) for l in (SNAP / "edges.jsonl").read_text(encoding="utf-8").splitlines()]
    computed = {r["stop_id"]: r for r in map(json.loads, (SNAP / "precomputed.jsonl").read_text(encoding="utf-8").splitlines())}
    claims = json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))

    g = nx.DiGraph()
    for e in edges:
        if e["type"] == "SF":
            g.add_edge(e["a"], e["b"], capacity=e["cap"])
    platforms = collections.defaultdict(list)
    meta = {}
    for n in nodes:
        if "Platform" in n["labels"] and "Node" in n["labels"]:
            platforms[n["stop_id"]].append(n["uid"])
            meta[n["stop_id"]] = n
    streets = collections.defaultdict(list)
    for n in nodes:
        if "Street" in n["labels"]:
            streets[n["cx"]].append(n["uid"])
    lift_stations = collections.defaultdict(set)
    for n in nodes:
        if "Lift" in n["labels"] and "Node" in n["labels"]:
            lift_stations[n["station_id"]].add(n["facility_id"])

    def k(sources, sinks):
        h = g.copy()
        for s in sources:
            h.add_edge("__S", s, capacity=float("inf"))
        for t in sinks:
            h.add_edge(t, "__T", capacity=float("inf"))
        return nx.maximum_flow_value(h, "__S", "__T")

    problems = []
    oracle = {}
    for stop, uids in sorted(platforms.items()):
        cx = meta[stop]["cx"]
        if not streets.get(cx):
            oracle[stop] = None
            continue
        kb, ke = k(streets[cx], uids), k(uids, streets[cx])
        oracle[stop] = (kb, ke)
        row = computed.get(stop, {})
        for d, val in (("board", kb), ("exit", ke)):
            fal = float("inf") if row.get(f"at_grade_{d}") else row.get(f"k_{d}")
            exp = float("inf") if val >= big else val
            if fal != exp:
                problems.append(f"{stop} {d}: FalkorDB sweep {fal} != NetworkX {exp}")

    def inf(v):
        return float("inf") if v >= big else v

    assessed = {s: v for s, v in oracle.items() if v is not None}
    step_free = {s for s, (kb, ke) in assessed.items() if meta[s]["wheelchair_boarding"] != 2 and kb and ke}
    single = {s for s in step_free if min(inf(assessed[s][0]), inf(assessed[s][1])) == 1}
    derived = {
        "platforms_modelled": len(platforms),
        "platforms_no_accessible_entrance": len(oracle) - len(assessed),
        "platforms_step_free": len(step_free),
        "platforms_lift_dependent": sum(1 for s in step_free if min(inf(assessed[s][0]), inf(assessed[s][1])) != float("inf")),
        "platforms_single_lift": len(single),
        "platforms_k1_board": sum(1 for kb, _ in assessed.values() if kb == 1),
        "platforms_k1_exit": sum(1 for _, ke in assessed.values() if ke == 1),
        "naive_two_lifts_but_k1": sum(1 for s in single if len(lift_stations[meta[s]["station_id"]]) >= 2),
    }
    for key, val in derived.items():
        if claims.get(key) != val:
            problems.append(f"claims.json {key}={claims.get(key)} but independently derived {val}")
    if claims.get("seed_sha256") != manifest["seed_sha256"]:
        problems.append("claims.json was computed from a different snapshot")

    for p in problems:
        print("MISMATCH:", p, file=sys.stderr)
    print(f"checked {len(assessed)} platforms x 2 directions with NetworkX; "
          f"{len(derived)} claim keys re-derived; {len(problems)} mismatches")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
