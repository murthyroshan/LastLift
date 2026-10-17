"""One more lift: where would a single new lift, built alongside an existing stairs or escalator run, have prevented
the most hours without a step-free route in 2025? (MS4; the remedy after the worst day and the Lift Ledger.)

    python scripts/one_lift.py      # writes data/one_lift.json and claims (onelift_*)

Exact pricing, no re-solve per candidate: in a state where a platform-direction has no step-free route (max-flow 0),
a new unit edge u -> v restores one exactly when u is reachable from the street and v reaches the platform in the
graph with the closed lifts removed (the residual graph of a zero flow). One search per (state, platform-direction)
prices every stairs/escalator run at once; the hours of that state are credited to every run that qualifies. The
top 20 runs are then checked by re-solving max-flow with the extra edge in every state they were credited for.
For contrast the naive objective is also counted: how many platform-directions' k would rise at baseline (residual
criterion on the baseline max-flow). Hours are 2025 calendar platform-direction-hours, recorded closures only
(lower bound). A candidate is a location only: nothing here says a lift can be built there.
"""
import json
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import history_replay as hr  # noqa: E402

from lastlift.flow import TOL, exact_maxflow  # noqa: E402
from lastlift.seed import latest_snapshot  # noqa: E402

Y0, Y1 = datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)


def reach(adj, start):
    seen, q = set(start), deque(start)
    while q:
        x = q.popleft()
        for y in adj.get(x, ()):
            if y not in seen:
                seen.add(y)
                q.append(y)
    return seen


def load():
    snap = latest_snapshot()
    nodes = [json.loads(x) for x in (snap / "nodes.jsonl").read_text(encoding="utf-8").splitlines()]
    edges = [json.loads(x) for x in (snap / "edges.jsonl").read_text(encoding="utf-8").splitlines()]
    cx_of = {n["uid"]: n.get("cx") for n in nodes}
    name = {n["uid"]: n.get("name") for n in nodes}
    sf, steps = defaultdict(list), defaultdict(list)
    for e in edges:
        cx = cx_of.get(e["a"])
        if e["type"] == "SF":
            sf[cx].append((e["eid"], e["a"], e["b"], e["cap"], e.get("facility_id") if e.get("kind") == "lift" else None))
        elif e["type"] == "STEP":
            steps[cx].append({"eid": e["eid"], "a": e["a"], "b": e["b"], "kind": e["kind"],
                              "pathway_ids": e.get("pathway_ids", [])})
    streets = defaultdict(list)
    plats = defaultdict(lambda: defaultdict(list))
    for n in nodes:
        if "Street" in n["labels"]:
            streets[n["cx"]].append(n["uid"])
        if "Platform" in n["labels"] and "Node" in n["labels"]:
            plats[n["cx"]][n["stop_id"]].append(n["uid"])
    return sf, steps, streets, plats, name


def qualifying(sf_edges, steps, src, dst, closed):
    """STEP runs u->v with u reachable from src and v reaching dst once `closed` lifts are out (flow 0 state)."""
    fwd, back = defaultdict(list), defaultdict(list)
    for eid, a, b, cap, fac in sf_edges:
        if fac and fac in closed:
            continue
        fwd[a].append(b)
        back[b].append(a)
    rs, rt = reach(fwd, src), reach(back, dst)
    return {s["eid"] for s in steps if s["a"] in rs and s["b"] in rt}


def baseline_gains(sf_edges, steps, src, dst):
    """Residual criterion on the baseline max-flow: runs whose parallel lift would raise k by one."""
    edges = [(eid, a, b, cap) for eid, a, b, cap, _ in sf_edges]
    value, flow = exact_maxflow(edges, src, dst)
    if value >= 1_000_000 or value == 0:
        return set()
    radj, rrev = defaultdict(list), defaultdict(list)
    for eid, a, b, cap in edges:
        f = flow.get(eid, 0)
        if f < cap - TOL:
            radj[a].append(b)
            rrev[b].append(a)
        if f > TOL:
            radj[b].append(a)
            rrev[a].append(b)
    rs, rt = reach(radj, src), reach(rrev, dst)
    return {s["eid"] for s in steps if s["a"] in rs and s["b"] in rt}


def main():
    net = json.loads((latest_snapshot() / "network.json").read_text(encoding="utf-8"))
    sf, steps, streets, plats, name = load()
    eps = hr.episodes(hr.merged_windows(), "out", hr.GAP_MIN)
    eps = {f: [(max(s, Y0), min(e, Y1), *r) for s, e, *r in es if e > Y0 and s < Y1] for f, es in eps.items()}
    modelled = set(net["lifts"])
    events = defaultdict(lambda: [set(), set()])
    for f, es in eps.items():
        if f in modelled:
            for s, e, *_ in es:
                events[s][1].add(f)
                events[e][0].add(f)
    dirs = []
    for stop, p in net["platform"].items():
        for d in ("board", "exit"):
            if p[d].get("minimal"):
                dirs.append((p["cx"], stop, d, [frozenset(x) for x in p[d]["minimal"]]))
    hours, credits = defaultdict(float), defaultdict(list)
    cache = {}
    closed = defaultdict(int)
    times = sorted(events)
    for t0, t1 in zip(times, times[1:]):
        opened, newly = events[t0]
        for f in opened:
            closed[f] -= 1
            if closed[f] <= 0:
                del closed[f]
        for f in newly:
            closed[f] += 1
        C = frozenset(closed)
        h = (t1 - t0).total_seconds() / 3600
        for cx, stop, d, sets in dirs:
            if not any(s <= C for s in sets):
                continue
            key = (cx, stop, d, C & frozenset(f for s in sets for f in s) | C)
            if key not in cache:
                src, dst = (streets[cx], plats[cx][stop]) if d == "board" else (plats[cx][stop], streets[cx])
                cache[key] = qualifying(sf[cx], steps[cx], src, dst, C)
            for eid in cache[key]:
                hours[eid] += h
                credits[eid].append((cx, stop, d, C, h))
    gains = defaultdict(int)
    for cx in steps:
        for stop, uids in plats[cx].items():
            for src, dst in ((streets[cx], uids), (uids, streets[cx])):
                if src and dst:
                    for eid in baseline_gains(sf[cx], steps[cx], src, dst):
                        gains[eid] += 1
    step_by_id = {s["eid"]: (cx, s) for cx, ss in steps.items() for s in ss}
    top = sorted(hours.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
    # exactness: re-solve max-flow with the extra unit edge for every credited state of the top 20
    checked = 0
    for eid, h in top:
        cx, s = step_by_id[eid]
        redo = 0.0
        for _cx, stop, d, C, hh in credits[eid]:
            edges = [(e, a, b, c) for e, a, b, c, fac in sf[cx] if not (fac and fac in C)]
            edges.append(("NEW", s["a"], s["b"], 1))
            src, dst = (streets[cx], plats[cx][stop]) if d == "board" else (plats[cx][stop], streets[cx])
            if exact_maxflow(edges, src, dst)[0] >= 1:
                redo += hh
        assert abs(redo - h) < 1e-6, (eid, redo, h)
        checked += 1

    def row(eid):
        cx, s = step_by_id[eid]
        return {"eid": eid, "pathway_ids": s["pathway_ids"], "kind": s["kind"], "complex": cx,
                "station": net["names"].get(cx, cx), "from": name.get(s["a"]), "to": name.get(s["b"]),
                "hours_2025": round(hours.get(eid, 0), 1), "k_gains_baseline": gains.get(eid, 0)}
    by_gain = sorted(gains.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    doc = {"year": 2025, "basis": "calendar platform-direction-hours, recorded closures (lower bound)",
           "top": [row(e) for e, _ in top[:10]], "top_by_baseline_gain": [row(e) for e, _ in by_gain],
           "candidates_with_hours": len(hours), "candidates_with_gain": len(gains), "exactness_checked": checked}
    (ROOT / "data" / "one_lift.json").write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                                                 encoding="utf-8", newline="\n")
    claims_path = ROOT / "claims.json"
    claims = {k: v for k, v in json.loads(claims_path.read_text(encoding="utf-8")).items() if not k.startswith("onelift_")}
    t, g = doc["top"][0], doc["top_by_baseline_gain"][0]
    claims.update({"onelift_best_station": t["station"], "onelift_best_hours": round(t["hours_2025"]),
                   "onelift_best_pathway": t["pathway_ids"][0] if t["pathway_ids"] else t["eid"],
                   "onelift_naive_station": g["station"], "onelift_naive_hours": round(g["hours_2025"]),
                   "onelift_candidates": len(gains), "onelift_exact_checked": checked})
    claims_path.write_text(json.dumps(claims, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    for r in doc["top"]:
        print(r["station"], r["pathway_ids"][:2], r["kind"], r["hours_2025"], "gains", r["k_gains_baseline"])
    print("naive top:", [(r["station"], r["pathway_ids"][:1], r["k_gains_baseline"], r["hours_2025"]) for r in doc["top_by_baseline_gain"][:3]])
    print("exactness checked", checked, "candidates", len(hours), len(gains))
    return 0


if __name__ == "__main__":
    sys.exit(main())
