"""Network and contingency sweep (M10): blast radius, conditional last lifts, all minimum cuts, N-2 pairs,
per-lift N-1 table, exact reliability and a network Monte-Carlo. Reads the base graph from FalkorDB.

    python scripts/network_sweep.py            # writes data/snapshots/<date>/network.json, claims.json
                                               # (net_*, n2_*, mincut_*, rel_* keys) and applies it to the graph

Every published number has an independent check, and the sweep records how often they agree:
  * journeys a lift breaks: dominator trees on the zone graph vs plain search on the full network;
  * all minimum cuts: Picard-Queyranne on the certified flow's residual graph vs every k-subset of lifts;
  * reliability: exact enumeration (checked against Monte-Carlo in the tests).
"""
import collections
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift import db, redundancy, state  # noqa: E402
from lastlift.cuts import Failures, all_min_cuts, brute_min_cuts, facility_sets  # noqa: E402
from lastlift.flow import exact_maxflow  # noqa: E402
from lastlift.network import Net  # noqa: E402
from lastlift.routing import Topology  # noqa: E402
from lastlift.seed import apply_network, latest_snapshot  # noqa: E402

Q_ASSUMED = 0.02            # uniform per-lift unavailability until the history gives empirical values (M11)
MC_QS = (0.01, 0.02, 0.05)
MC_SAMPLES = 1000
MC_SEED = 20261020


def network_part(net: Net, log):
    started = time.time()
    od = net.od()
    times = net.travel_times()
    imp = net.n1()
    dominates_for = {f: sorted(s) for f, s in net.dominates_for.items()}
    log(f"n1 by dominators: {time.time() - started:.1f}s")
    t = time.time()
    agree = sum(net.witness(f) == imp[f].broken for f in sorted(net.units))
    log(f"witness: {agree}/{len(net.units)} agree ({time.time() - t:.1f}s)")

    # detours for lifts whose closure breaks no journey (the network re-routes around them)
    t = time.time()
    slow = collections.defaultdict(list)            # facility -> [extra seconds per slowed journey]
    for a in net.stations:
        root = net.street[a]
        used = net.tree_lifts(root)
        base = net.times(root)
        for f in sorted(used):
            if imp[f].broken:
                continue
            after = net.times(root, net.banned_nodes([f]))
            for b in net.stations:
                tb = net.street[b]
                if b != a and tb in base and tb in after and after[tb] > base[tb]:
                    slow[f].append(after[tb] - base[tb])
    log(f"detours: {time.time() - t:.1f}s")

    # conditional last lifts: with f1 closed, which other lift now breaks journeys it did not break before
    t = time.time()
    st_of = {f: net.unit_station.get(us[0], "") for f, us in net.units.items()}
    conditional = []
    for f1 in sorted(net.units):
        after = net.n1([f1])
        for f2, i2 in after.items():
            new = i2.broken - imp[f2].broken
            if new:
                conditional.append({"closed": f1, "lift": f2, "journeys": len(new), "cut_off": i2.cut_off,
                                    "same_station": st_of[f1] == st_of[f2], "station_closed": st_of[f1],
                                    "station_lift": st_of[f2]})
    log(f"conditional: {len(conditional)} ordered pairs ({time.time() - t:.1f}s)")

    lifts = {}
    for f in sorted(net.units):
        s = slow.get(f, [])
        lifts[f] = {"station_id": st_of[f], "od_cut": len(imp[f].broken), "cut_off": imp[f].cut_off,
                    "dominates_for": dominates_for.get(f, []), "od_slow": len(s),
                    "detour_max_s": max(s) if s else 0, "detour_mean_s": round(statistics.mean(s), 1) if s else 0}
    return od, times, lifts, conditional, agree


def platform_part(g, log):
    started = time.time()
    snap = latest_snapshot()
    rows = [json.loads(x) for x in (snap / "precomputed.jsonl").read_text(encoding="utf-8").splitlines()]
    streets = collections.defaultdict(list)
    for uid, cx in g.ro_query("MATCH (s:Street) RETURN s.uid, s.cx").result_set:
        streets[cx].append(uid)
    cache, stats = {}, collections.Counter()
    platform, pairs, n1 = {}, collections.defaultdict(list), {}
    for r in rows:
        if r.get("status"):
            continue
        cx = r["cx"]
        if cx not in cache:
            cache[cx] = redundancy.complex_edges(g, cx)
        edges, lf = cache[cx]
        by_fac = collections.defaultdict(set)
        for eid, f in lf.items():
            by_fac[f].add(eid)
        entry = {}
        for d in ("board", "exit"):
            src, dst = (streets[cx], r["uids"]) if d == "board" else (r["uids"], streets[cx])
            k = r.get(f"k_{d}")
            if r.get(f"at_grade_{d}") or not k:
                entry[d] = {"k": None if r.get(f"at_grade_{d}") else k, "at_grade": bool(r.get(f"at_grade_{d}"))}
                continue
            value, flow = exact_maxflow(edges, src, dst)
            assert int(value) == k, (r["stop_id"], d)
            cuts, complete = all_min_cuts(edges, flow, src, dst, lf)
            stats["mincut_dirs"] += 1
            stats["mincut_pq_eq_brute" if cuts == brute_min_cuts(edges, lf, src, dst, k) else "mincut_pq_ne_brute"] += 1
            stats["mincut_incomplete"] += not complete
            fs = facility_sets(cuts, lf)
            fail = Failures(edges, lf, src, dst)
            stats["rel_dirs_exact" if fail.complete else "rel_dirs_inexact"] += 1
            for p in fail.pairs():
                pairs[p].append({"stop_id": r["stop_id"], "dir": d, "station_id": r["station_id"]})
            without = {}
            for f in sorted(by_fac):
                v, _ = exact_maxflow([e for e in edges if e[0] not in by_fac[f]], src, dst)
                if int(v) != k:
                    without[f] = int(v)
            entry[d] = {"k": k, "at_grade": False, "mincuts": [list(c) for c in fs], "relevant": fail.facilities,
                        "rel_counts": fail.counts, "minimal": [list(c) for c in fail.minimal],
                        "k_without": without}
        platform[r["stop_id"]] = {"station_id": r["station_id"], "cx": cx, **entry}
        n1.setdefault(cx, {"facilities": sorted(by_fac), "platforms": []})["platforms"].append(r["stop_id"])
    log(f"platform part: {time.time() - started:.1f}s {dict(stats)}")
    pair_rows = [{"a": a, "b": b, "dirs": ds, "n": len(ds)} for (a, b), ds in sorted(pairs.items())]
    return platform, pair_rows, n1, stats


def monte_carlo(net: Net, log):
    rng = random.Random(MC_SEED)
    facilities = sorted(net.units)
    total = len(net.stations) * (len(net.stations) - 1)
    out = {}
    for q in MC_QS:
        t = time.time()
        shares = []
        for _ in range(MC_SAMPLES):
            down = [f for f in facilities if rng.random() < q]
            od = net.od(down)
            shares.append(sum(len(v) for v in od.values()) / total)
        m = statistics.mean(shares)
        half = 1.96 * statistics.stdev(shares) / MC_SAMPLES ** 0.5
        out[str(q)] = {"mean": round(m, 5), "ci95": [round(m - half, 5), round(m + half, 5)], "samples": MC_SAMPLES}
        log(f"monte carlo q={q}: {m:.4f} ({time.time() - t:.1f}s)")
    return {"seed": MC_SEED, "q": out, "unit": "share of ordered station pairs reachable step-free"}


def main():
    log = lambda m: print(m, flush=True)
    base = state.graph_name("base")
    g = db.client().select_graph(base)
    net = Net(Topology.from_graph(g))
    od, times, lifts, conditional, agree = network_part(net, log)
    platform, pair_rows, n1, pstats = platform_part(g, log)
    mc = monte_carlo(net, log)
    snap = latest_snapshot()
    manifest = json.loads((snap / "MANIFEST.json").read_text(encoding="utf-8"))
    doc = {"seed_sha256": manifest["seed_sha256"], "rules_version": manifest["rules_version"],
           "q_assumed": Q_ASSUMED, "stations": net.stations, "names": net.names,
           "od_base_s": times, "lifts": lifts, "conditional": conditional, "pairs": pair_rows,
           "platform": platform, "n1": n1, "monte_carlo": mc}
    (snap / "network.json").write_text(json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n",
                                       encoding="utf-8", newline="\n")

    claims_path = ROOT / "claims.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    claims = {k: v for k, v in claims.items() if not k.startswith(("net_", "n2_", "mincut_", "rel_"))}
    spof_net = {f for f, x in lifts.items() if x["od_cut"]}
    spof_platform = {f for p in platform.values() for d in ("board", "exit")
                     for f in (p[d].get("minimal") and [c[0] for c in p[d]["minimal"] if len(c) == 1] or [])}
    rescued = sorted(spof_platform - spof_net)
    worst = [lifts[f]["detour_max_s"] for f in rescued if lifts[f]["detour_max_s"]]
    cond_pairs = {tuple(sorted((c["closed"], c["lift"]))) for c in conditional}
    top = max(pair_rows, key=lambda p: (p["n"], p["a"])) if pair_rows else None
    n_pairs = len(net.stations) * (len(net.stations) - 1)
    claims.update({
        "net_origins": len(net.stations), "net_od_pairs": n_pairs,
        "net_od_reachable_base": sum(len(v) for v in od.values()),
        "net_spof_lifts": len(spof_net),
        "net_spof_journeys_each": sorted({lifts[f]["od_cut"] for f in spof_net}),
        "net_cut_off_stations": len({s for f in spof_net for s in lifts[f]["cut_off"]}),
        "net_platform_spof_lifts": len(spof_platform),
        "net_rescued_lifts": len(rescued),
        "net_detour_median_min": round(statistics.median(worst) / 60, 1) if worst else 0,
        "net_detour_max_min": round(max(worst) / 60, 1) if worst else 0,
        "net_detour_max_lift": max(rescued, key=lambda f: (lifts[f]["detour_max_s"], f)) if worst else None,
        "net_dominator_eq_witness": agree, "net_dominator_lifts": len(net.units),
        "net_conditional_ordered": len(conditional), "net_conditional_pairs": len(cond_pairs),
        "net_conditional_cross_station": sum(1 for c in conditional if not c["same_station"]),
        "net_mc_reachable_q02": mc["q"]["0.02"]["mean"],
        "n2_critical_pairs": len(pair_rows),
        "n2_top_pair": f"{top['a']}+{top['b']}" if top else None, "n2_top_pair_dirs": top["n"] if top else 0,
        "mincut_dirs": pstats["mincut_dirs"], "mincut_pq_eq_brute": pstats["mincut_pq_eq_brute"],
        "mincut_multi": sum(1 for p in platform.values() for d in ("board", "exit")
                            if len(p[d].get("mincuts") or []) > 1),
        "rel_dirs_exact": pstats["rel_dirs_exact"], "rel_q_assumed": Q_ASSUMED,
    })
    claims_path.write_text(json.dumps(claims, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in claims.items() if k.startswith(("net_", "n2_", "mincut_", "rel_"))}, indent=1))
    print(f"applied to {base}: {apply_network(base, snap)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
