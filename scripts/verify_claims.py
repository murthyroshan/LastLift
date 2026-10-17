"""Independently re-derive LastLift's numbers from the committed snapshot files (no FalkorDB).

    python scripts/verify_claims.py

1. Rebuilds the step-free network from data/snapshots/<date>/{nodes,edges}.jsonl,
2. recomputes board/exit k for every platform with NetworkX,
3. re-derives the single points of failure: for every k = 1 platform-direction, removes each lift
   in the complex in turn and tests reachability,
4. compares all of it with precomputed.jsonl (the FalkorDB sweep) and re-derives every core key of
   claims.json from scratch. Exits non-zero on any mismatch.
"""
import collections
import itertools
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
    cx_of = {n["uid"]: n.get("cx") for n in nodes}
    lift_edges = collections.defaultdict(list)          # cx -> [(a, b, facility_id)]
    for e in edges:
        if e["type"] == "SF" and e["kind"] == "lift":
            lift_edges[cx_of[e["a"]]].append((e["a"], e["b"], e["facility_id"]))
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

    adj = collections.defaultdict(list)                 # step-free adjacency, for reachability
    for e in edges:
        if e["type"] == "SF":
            adj[e["a"]].append(e["b"])

    def reachable(sources, sinks, removed):
        seen, todo, sinks = set(sources), list(sources), set(sinks)
        while todo:
            u = todo.pop()
            if u in sinks:
                return True
            for v in adj[u]:
                if v not in seen and (u, v) != removed:
                    seen.add(v)
                    todo.append(v)
        return False

    spof = {"board": set(), "exit": set()}
    for stop, ks in sorted(oracle.items()):
        if ks is None:
            continue
        cx, uids = meta[stop]["cx"], platforms[stop]
        for d, val in (("board", ks[0]), ("exit", ks[1])):
            found = set()
            if val == 1:
                src, dst = (streets[cx], uids) if d == "board" else (uids, streets[cx])
                for a, b, fid in lift_edges[cx]:
                    if not reachable(src, dst, (a, b)):
                        found.add(fid)
            spof[d] |= found
            fal = set(computed.get(stop, {}).get(f"spof_{d}", []))
            if fal != found:
                problems.append(f"{stop} {d}: FalkorDB sweep SPOFs {sorted(fal)} != NetworkX {sorted(found)}")

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
        "spof_lifts": len(spof["board"] | spof["exit"]),
        "spof_lifts_exit_only": len(spof["exit"] - spof["board"]),
    }
    derived.update(network_claims(nodes, edges))
    for key, val in derived.items():
        if claims.get(key) != val:
            problems.append(f"claims.json {key}={claims.get(key)} but independently derived {val}")
    if claims.get("seed_sha256") != manifest["seed_sha256"]:
        problems.append("claims.json was computed from a different snapshot")

    for p in problems:
        print("MISMATCH:", p, file=sys.stderr)
    print(f"checked {len(assessed)} platforms x 2 directions with NetworkX "
          f"(k and single-point-of-failure lifts); "
          f"{len(derived)} claim keys re-derived; {len(problems)} mismatches")
    return 1 if problems else 0


def network_claims(nodes, edges):
    """The network numbers with NetworkX alone: its own dominator implementation on the full SF + RIDE graph
    (no zone contraction), and N-2 pairs by brute force over pairs of facilities in each complex."""
    g = nx.DiGraph()
    g.add_nodes_from(n["uid"] for n in nodes)
    for e in edges:
        if e["type"] in ("SF", "RIDE"):
            g.add_edge(e["a"], e["b"])
    street = {n["station_id"]: n["uid"] for n in nodes if "Street" in n["labels"]}
    unit_fac = {e["b"]: e["facility_id"] for e in edges if e["type"] == "SF" and e.get("kind") == "lift"}
    units = collections.defaultdict(list)
    for out, f in unit_fac.items():
        units[f].append(out)
    broken = collections.defaultdict(set)
    for a, root in street.items():
        idom = nx.immediate_dominators(g, root)
        for b, t in street.items():
            if b == a or t not in idom:
                continue
            x = idom[t]
            while x != root:
                if x in unit_fac and len(units[unit_fac[x]]) == 1:
                    broken[unit_fac[x]].add((a, b))
                x = idom[x]
    for f, outs in units.items():                      # facilities with several units: remove them all
        if len(outs) > 1:
            h = g.copy()
            h.remove_nodes_from(outs)
            for a, root in street.items():
                reach = nx.descendants(h, root)
                full = nx.descendants(g, root)
                broken[f] |= {(a, b) for b, t in street.items() if b != a and t in full and t not in reach}
    reach_all = {a: {b for b, t in street.items() if b != a and t in nx.descendants(g, r)} for a, r in street.items()}
    spof = {f for f, s in broken.items() if s}
    cut_off = set()
    for f in spof:
        for s in street:
            out_ = {(a, b) for a, b in broken[f] if a == s}
            in_ = {(a, b) for a, b in broken[f] if b == s}
            if reach_all[s] and len(out_) == len(reach_all[s]) and len(in_) == sum(1 for a in street if s in reach_all[a]):
                cut_off.add(s)

    # N-2: facility pairs within a complex, neither alone cutting a platform-direction, both together cutting it
    sf = collections.defaultdict(list)
    cx_of = {n["uid"]: n.get("cx") for n in nodes}
    for e in edges:
        if e["type"] == "SF":
            sf[cx_of[e["a"]]].append(e)
    streets = collections.defaultdict(list)
    plats = collections.defaultdict(lambda: collections.defaultdict(list))
    for n in nodes:
        if "Street" in n["labels"]:
            streets[n["cx"]].append(n["uid"])
        if "Platform" in n["labels"] and "Node" in n["labels"]:
            plats[n["cx"]][n["stop_id"]].append(n["uid"])
    pairs = set()
    for cx, es in sf.items():
        if not streets.get(cx):
            continue
        h = nx.DiGraph()
        h.add_edges_from((e["a"], e["b"]) for e in es)
        facs = sorted({e["facility_id"] for e in es if e.get("kind") == "lift"})
        lift_out = collections.defaultdict(list)
        for e in es:
            if e.get("kind") == "lift":
                lift_out[e["facility_id"]].append(e["b"])

        def ok(src, dst, closed):
            k = h.copy()
            k.remove_nodes_from([o for f in closed for o in lift_out[f]])
            seen = set().union(*(nx.descendants(k, s) | {s} for s in src if s in k))
            return bool(seen & set(dst))
        for stop, uids in plats[cx].items():
            for src, dst in ((streets[cx], uids), (uids, streets[cx])):
                if not ok(src, dst, ()):
                    continue
                single = {f for f in facs if not ok(src, dst, (f,))}
                for f1, f2 in itertools.combinations([f for f in facs if f not in single], 2):
                    if not ok(src, dst, (f1, f2)):
                        pairs.add((f1, f2))
    return {"net_spof_lifts": len(spof), "net_cut_off_stations": len(cut_off),
            "net_od_reachable_base": sum(len(v) for v in reach_all.values()), "n2_critical_pairs": len(pairs)}


if __name__ == "__main__":
    sys.exit(main())
