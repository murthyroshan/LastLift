"""Baseline redundancy sweep: board and exit k for every modelled platform, computed in FalkorDB.

    python scripts/analyze.py                 # sweep the base graph, write precomputed.jsonl + claims.json
    python scripts/analyze.py --oracle        # also cross-check every value against NetworkX

For each platform (a GTFS stop_id; split stops count both halves), each direction:
  1. FalkorDB algo.maxFlow over the single step-free relationship type SF,
  2. certification of the returned flow (lastlift.flow.certify); exact repair if it fails,
  3. the minimum cut (lift facilities a finite k depends on),
  4. a k-path decomposition checked by the independent proof checker (lastlift.checker),
  5. optionally, an independent NetworkX value.
Results are written back to the graph (k_board_base, k_exit_base, cut_*), to
data/snapshots/<date>/precomputed.jsonl, and the headline numbers to claims.json.
"""
import argparse
import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift import db  # noqa: E402
from lastlift import redundancy  # noqa: E402
from lastlift.config import settings  # noqa: E402
from lastlift.seed import latest_snapshot  # noqa: E402



def networkx_value(edges, sources, sinks):
    import networkx as nx
    g = nx.DiGraph()
    for eid, u, v, cap in edges:
        g.add_edge(u, v, capacity=cap)
    for s in sources:
        g.add_edge("__S__", s, capacity=float("inf"))
    for t in sinks:
        g.add_edge(t, "__T__", capacity=float("inf"))
    return nx.maximum_flow_value(g, "__S__", "__T__")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default=settings.graph("base"))
    ap.add_argument("--oracle", action="store_true")
    args = ap.parse_args(argv)
    snapshot = latest_snapshot()
    manifest = json.loads((snapshot / "MANIFEST.json").read_text(encoding="utf-8"))
    big = manifest["big"]
    g = db.client().select_graph(args.graph)

    platforms = collections.defaultdict(list)
    meta = {}
    for uid, stop_id, cx, wb, station, name in g.ro_query(
            "MATCH (p:Node:Platform) RETURN p.uid, p.stop_id, p.cx, p.wheelchair_boarding, p.station_id, p.name").result_set:
        platforms[stop_id].append(uid)
        meta[stop_id] = {"cx": cx, "wheelchair_boarding": wb, "station_id": station, "name": name}
    streets = collections.defaultdict(list)
    for uid, cx in g.ro_query("MATCH (s:Street) RETURN s.uid, s.cx").result_set:
        streets[cx].append(uid)
    lifts_per_station = collections.Counter()
    for st, n in g.ro_query("MATCH (l:Node:Lift) RETURN l.station_id, count(DISTINCT l.facility_id)").result_set:
        lifts_per_station[st] = n

    cx_cache = {}
    stats = collections.Counter()
    rows = []
    started = time.time()
    for stop_id in sorted(platforms):
        m = meta[stop_id]
        cx = m["cx"]
        row = {"stop_id": stop_id, "uids": sorted(platforms[stop_id]), **m}
        if not streets.get(cx):
            row["status"] = "no_accessible_entrance"
            rows.append(row)
            continue
        if cx not in cx_cache:
            cx_cache[cx] = redundancy.complex_edges(g, cx)
        edges, lift_fac = cx_cache[cx]
        result = redundancy.platform(g, cx, platforms[stop_id], streets[cx], edges, lift_fac)
        for d in ("board", "exit"):
            r = result[d]
            stats["maxflow_calls"] += 1
            stats["falkordb_first_pass_exact" if r.outcome == "exact" else "falkordb_repaired"] += 1
            row[f"k_{d}"] = r.k
            row[f"at_grade_{d}"] = r.at_grade
            if r.k:
                row[f"cut_{d}"] = r.cut_facilities
                stats["checker_accepted" if r.proof == "accepted" else "checker_rejected"] += 1
                if r.proof != "accepted":
                    row[f"checker_{d}"] = r.proof
            if r.spof_facilities:
                row[f"spof_{d}"] = r.spof_facilities
            if args.oracle:
                src, dst = (streets[cx], platforms[stop_id]) if d == "board" else (platforms[stop_id], streets[cx])
                value = big if r.at_grade else (r.k or 0)
                ox = networkx_value(edges, src, dst)
                same = (ox >= big and r.at_grade) or abs(ox - value) < 1e-6
                stats["networkx_equal" if same else "networkx_mismatch"] += 1
        rows.append(row)
    elapsed = time.time() - started

    def k_of(r, d):
        return float("inf") if r.get(f"at_grade_{d}") else r.get(f"k_{d}")

    assessed = [r for r in rows if r.get("status") != "no_accessible_entrance"]
    step_free = [r for r in assessed if r["wheelchair_boarding"] != 2 and k_of(r, "board") and k_of(r, "exit")]
    lift_dependent = [r for r in step_free if min(k_of(r, "board"), k_of(r, "exit")) != float("inf")]
    single = [r for r in step_free if min(k_of(r, "board"), k_of(r, "exit")) == 1]
    spof_b = {f for r in assessed for f in r.get("spof_board", [])}
    spof_e = {f for r in assessed for f in r.get("spof_exit", [])}

    def hist(d):
        c = collections.Counter("at_grade" if r.get(f"at_grade_{d}") else str(r.get(f"k_{d}")) for r in assessed)
        return dict(sorted(c.items()))

    claims = {
        "feed_version": manifest["feed_version"], "gtfs_sha256": manifest["source"]["sha256"],
        "seed_sha256": manifest["seed_sha256"], "snapshot_id": snapshot.name,
        "platforms_modelled": len(platforms),
        "platforms_no_accessible_entrance": len(rows) - len(assessed),
        "platforms_step_free": len(step_free),
        "platforms_lift_dependent": len(lift_dependent),
        "platforms_single_lift": len(single),
        "platforms_k1_board": sum(1 for r in assessed if r.get("k_board") == 1),
        "platforms_k1_exit": sum(1 for r in assessed if r.get("k_exit") == 1),
        "k_hist_board": hist("board"), "k_hist_exit": hist("exit"),
        "spof_lifts": len(spof_b | spof_e), "spof_lifts_exit_only": len(spof_e - spof_b),
        "naive_two_lifts_but_k1": sum(1 for r in single if lifts_per_station[r["station_id"]] >= 2),
        "maxflow_calls": stats["maxflow_calls"],
        "falkordb_first_pass_exact": stats["falkordb_first_pass_exact"],
        "falkordb_repaired": stats["falkordb_repaired"],
        "falkordb_certified": stats["falkordb_first_pass_exact"] + stats["falkordb_repaired"],
        "checker_accepted": stats["checker_accepted"], "checker_rejected": stats["checker_rejected"],
        "sweep_seconds": round(elapsed, 1),
    }
    if args.oracle:
        claims["falkordb_eq_networkx"] = stats["networkx_equal"]
        claims["networkx_mismatch"] = stats["networkx_mismatch"]

    out = snapshot / "precomputed.jsonl"
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")
    (ROOT / "claims.json").write_text(json.dumps(claims, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    from lastlift.seed import apply_precomputed
    apply_precomputed(args.graph, snapshot)
    print(json.dumps({k: claims[k] for k in ("maxflow_calls", "falkordb_first_pass_exact", "falkordb_repaired",
                                             "falkordb_certified", "checker_accepted",
                                             "checker_rejected", "sweep_seconds")}
                     | ({"falkordb_eq_networkx": claims.get("falkordb_eq_networkx"),
                         "networkx_mismatch": claims.get("networkx_mismatch")} if args.oracle else {}), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
