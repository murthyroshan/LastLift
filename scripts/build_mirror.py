"""Build the static mirror the website falls back to when the API is asleep or blocked.

    python scripts/build_mirror.py            # writes web/public/m/ and web/public/claims.json

Everything comes from the same tools the API serves, on the frozen demo scope:
  m/state.json            current closures, repair priority, eval summary, snapshot ids
  m/stations.json         every station with pathway data: platforms, single-lift and lost counts
  m/station/<id>.json     platform_redundancy + the station graph contract (board and exit)
  m/whatif/<fid>.json     what_if_close for the story lifts + the station graph under that simulation
  m/queries.json          the Cypher of every Q_* constant (for the query drawer)
  m/contingency.json      network blast radius, N-2 critical pairs, conditional last lifts, the travel-time matrix,
                          network_impact and repair_order on the demo scope (from the network sweep)
  m/cuts/<id>.json        per platform-direction: every minimum cut, reliability counts, the per-lift N-1 table
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift import db, queries, state, station_view, tools  # noqa: E402

OUT = ROOT / "web" / "public" / "m"
STORY_WHATIFS = [("place-alfcl", "813"), ("place-dwnxg", "891"), ("place-knncl", "866"),
                 ("place-rbmnl", "884"), ("place-chncl", "922")]


def write(path: Path, data) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
    return len(text)


def main():
    started = time.time()
    tools.prepare_scope("demo")
    claims = json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))
    (ROOT / "web" / "public" / "claims.json").write_bytes((ROOT / "claims.json").read_bytes())
    g = db.client().select_graph(state.graph_name("demo"))
    meta = g.ro_query(queries.Q_META).result_set[0]
    write(OUT / "state.json", {
        "scope": "demo", "snapshot": {"id": meta[0], "seed_sha256": meta[1]},
        "closures": tools.current_closures("demo"), "priority": tools.repair_priority("demo", limit=200),
        "eval": {k: v for k, v in claims.items() if k.startswith(("live_", "static_"))},
    })
    write(OUT / "queries.json", {n: getattr(queries, n) for n in sorted(dir(queries)) if n.startswith("Q_")})
    rows = g.ro_query("MATCH (s:Station) WHERE s.has_pathways RETURN s.uid, s.name ORDER BY s.name").result_set
    stations, total = [], 0
    for sid, name in rows:
        red = tools.platform_redundancy(sid, "demo")
        graphs = {d: station_view.view(sid, d, "demo") for d in ("board", "exit")}
        total += write(OUT / "station" / f"{sid}.json", {"redundancy": red, "graph": graphs})
        plats = (red.get("data") or {}).get("platforms", [])
        k = lambda p, d: (p.get(d) or {}).get("k")
        stations.append({
            "id": sid, "name": name, "platforms": len(plats),
            "lost": sum(1 for p in plats if 0 in (k(p, "board"), k(p, "exit"))),
            "single": sum(1 for p in plats if 1 in (k(p, "board"), k(p, "exit")) and 0 not in (k(p, "board"), k(p, "exit"))),
            "closed": (red.get("data") or {}).get("closed_here", []),
        })
        print(f"{sid}: {len(plats)} platforms", flush=True)
    write(OUT / "stations.json", stations)
    for sid, fid in STORY_WHATIFS:
        wi = tools.what_if_close([fid], "demo")
        copy = (wi.get("data") or {}).get("copy")
        graphs = {d: station_view.view(sid, d, "demo", scenario=copy) for d in ("board", "exit")} if copy else {}
        total += write(OUT / "whatif" / f"{fid}.json", {"station": sid, "whatif": wi, "graph": graphs})
    # repairs page: ticket drafts for lifts that need action now (tiers 1-2), reroutes for every lost platform
    ranked = (tools.repair_priority("demo", limit=200).get("data") or {}).get("ranked", [])
    for r in [r for r in ranked if r["tier"] in (1, 2)]:
        total += write(OUT / "ticket" / f"{r['facility_id']}.json", tools.draft_action(r["facility_id"], "demo"))
    for lp in (tools.current_closures("demo").get("data") or {}).get("platforms_lost", []):
        routes = {"exit": tools.step_free_route(lp["station_id"], from_platform=lp["stop_id"], scope="demo"),
                  "board": tools.step_free_route(lp["station_id"], to_platform=lp["stop_id"], scope="demo")}
        total += write(OUT / "reroute" / f"{lp['stop_id']}.json", {"platform": lp, **routes})
    import csv
    rows = list(csv.DictReader((ROOT / "validation" / "eval_live.csv").open(encoding="utf-8")))
    keep = ("gold_id", "facility_ids", "stations", "mbta_board_class", "mbta_exit_class", "exp_verdict",
            "labeller_notes", "model_verdict", "model_entrances_cut", "model_alt_lifts", "match")
    write(OUT / "eval.json", [{k: r[k] for k in keep} for r in rows])
    from lastlift.wording import DISCLAIMERS
    write(OUT / "disclaimers.json", DISCLAIMERS)
    total += contingency()
    total += history()
    total += operations()
    total += system_and_map()
    if (ROOT / "data" / "one_lift.json").is_file():
        total += write(OUT / "one_lift.json", json.loads((ROOT / "data" / "one_lift.json").read_text(encoding="utf-8")))
    if (ROOT / "data" / "worst_day.json").is_file():
        total += write(OUT / "worst_day.json", json.loads((ROOT / "data" / "worst_day.json").read_text(encoding="utf-8")))
    print(f"mirror: {len(stations)} stations, {len(STORY_WHATIFS)} what-ifs, {total // 1024} KB, "
          f"{time.time() - started:.0f} s")
    return 0


def contingency() -> int:
    from lastlift.seed import latest_snapshot
    doc = json.loads((latest_snapshot() / "network.json").read_text(encoding="utf-8"))
    names = doc["names"]
    st = doc["stations"]
    matrix = [[None if a == b else (round(doc["od_base_s"][a][b] / 60, 1) if b in doc["od_base_s"][a] else -1)
               for b in st] for a in st]
    lifts = doc["lifts"]
    total = write(OUT / "contingency.json", {
        "q_assumed": doc["q_assumed"], "stations": st, "names": names, "minutes": matrix,
        "network_spof": [{"facility_id": f, **x} for f, x in sorted(lifts.items(), key=lambda kv: (-kv[1]["od_cut"], kv[0]))
                         if x["od_cut"]],
        "rescued": [{"facility_id": f, **x} for f, x in sorted(lifts.items(), key=lambda kv: (-kv[1]["detour_max_s"], kv[0]))
                    if not x["od_cut"] and x["od_slow"]],
        "pairs": doc["pairs"], "conditional": doc["conditional"], "monte_carlo": doc["monte_carlo"],
        "now": tools.network_impact(scope="demo"), "order": tools.repair_order(scope="demo"),
    })
    by_station = {}
    for stop, p in doc["platform"].items():
        by_station.setdefault(p["station_id"], {})[stop] = p
    for sid, plats in by_station.items():
        total += write(OUT / "cuts" / f"{sid}.json", {"q_assumed": doc["q_assumed"], "platforms": plats})
    return total


def _bin(k, at_grade, no_entrance):
    """The Count's bins, defined exactly as claims.json counts them (scripts/analyze.py)."""
    if no_entrance:
        return "none"
    if at_grade:
        return "grade"
    if k is None:
        return "none"
    return "lost" if k == 0 else "one" if k == 1 else "many"


def system_and_map() -> int:
    """m/system.json: every modelled platform's bin, at baseline and now (The Count); m/map.json: every station at
    its coordinates with its worst bin, closures and new last lifts, and the station-to-station ride links."""
    g = db.client().select_graph(state.graph_name("demo"))
    rows = g.ro_query(
        "MATCH (p:Node:Platform) WITH p.stop_id AS stop, head(collect(p)) AS p "
        "RETURN stop, p.station_id, p.name, p.platform_name, p.k_board_base, p.k_exit_base, p.k_board, p.k_exit, "
        "coalesce(p.at_grade_board, false), coalesce(p.at_grade_exit, false), "
        "coalesce(p.at_grade_board_now, false), coalesce(p.at_grade_exit_now, false), "
        "coalesce(p.no_accessible_entrance, false) ORDER BY stop").result_set
    platforms = []
    for stop, sid, name, pname, kbb, keb, kb, ke, agb, age, agbn, agen, noe in rows:
        platforms.append({"stop": stop, "station": sid, "name": " ".join(x for x in (name, pname) if x),
                          "board": {"base": _bin(kbb, agb, noe), "now": _bin(kb, agbn, noe)},
                          "exit": {"base": _bin(keb, age, noe), "now": _bin(ke, agen, noe)}})
    total = write(OUT / "system.json", {"platforms": platforms})
    order = {"lost": 0, "one": 1, "many": 2, "grade": 3}
    worst = {}
    for p in platforms:
        for when in ("base", "now"):
            bins = [p[d][when] for d in ("board", "exit") if p[d][when] in order]
            if bins:
                w = min(bins, key=order.get)
                cur = worst.setdefault(p["station"], {}).get(when)
                if cur is None or order[w] < order[cur]:
                    worst[p["station"]][when] = w
    closed = {}
    for fid, sid in g.ro_query("MATCH (l:Lift)-[:SF_CLOSED]->() RETURN DISTINCT l.facility_id, l.station_id").result_set:
        closed.setdefault(sid, []).append(fid)
    newly = {r[0] for r in g.ro_query("MATCH (p:Node:Platform)-[n:DEPENDS_NOW]->(l:Lift) "
                                      "WHERE NOT (p)-[:DEPENDS_ON {dir:n.dir}]->(l) RETURN DISTINCT p.station_id").result_set}
    stations = [{"id": sid, "name": name, "lat": round(lat, 5), "lon": round(lon, 5), "data": bool(hp),
                 "base": worst.get(sid, {}).get("base"), "now": worst.get(sid, {}).get("now"),
                 "closed": sorted(closed.get(sid, [])), "new_last": sid in newly}
                for sid, name, lat, lon, hp in g.ro_query(
                    "MATCH (s:Station) WHERE s.lat IS NOT NULL RETURN s.uid, s.name, s.lat, s.lon, s.has_pathways "
                    "ORDER BY s.uid").result_set]
    links = [{"a": a, "b": b, "rail": bool(rail)} for a, b, rail in g.ro_query(
        "MATCH (x:Platform)-[r:RIDE]->(y:Platform) WHERE x.station_id < y.station_id "
        "RETURN DISTINCT x.station_id, y.station_id, max(CASE WHEN r.route_type <> '3' THEN 1 ELSE 0 END) "
        "ORDER BY x.station_id, y.station_id").result_set]
    total += write(OUT / "map.json", {"stations": stations, "links": links})
    return total


def operations() -> int:
    """m/ops.json: one tick of the operations agents on the demo scope (assessments, proposals, rider notices in dry
    run). The live inbox comes from the API; this snapshot keeps the page readable when the API is asleep."""
    import asyncio
    from lastlift.agents import roles
    g = db.client().select_graph(state.graph_name("demo"))
    g.query("MATCH (n) WHERE n:Assessment OR n:ActionProposal DETACH DELETE n")
    g.query("MATCH (n:Notice) DETACH DELETE n")
    t = asyncio.run(roles.tick("demo"))
    keep = ("facility_id", "station_id", "playbook", "verdict", "chronic", "targets", "finds", "proposals")
    return write(OUT / "ops.json", {
        "assessments": [{k: a.get(k) for k in keep} for a in t["assessments"]],
        "notices": [{k: n.get(k) for k in ("station_id", "kind", "title", "body", "topic")} for n in t["notices"]
                    if n.get("kind")],
        "policy": roles.POLICY,
        "events": [{k: e.get(k) for k in ("agent", "type", "tool", "facility_id", "playbook", "kind", "ok")}
                   for e in t["events"]]})


def history() -> int:
    """m/history/<station>.json: closures since 2024 for the station's platforms and lifts (the Lift Ledger), and
    m/history/lifts.json for the repairs table. Historical frequencies only, never a forecast."""
    hdir = ROOT / "data" / "history"
    if not (hdir / "replay.json").is_file():
        return 0
    from lastlift.seed import latest_snapshot
    rep = json.loads((hdir / "replay.json").read_text(encoding="utf-8"))
    net = json.loads((latest_snapshot() / "network.json").read_text(encoding="utf-8"))
    station_of_stop = {s: p["station_id"] for s, p in net["platform"].items()}
    station_of_lift = {f: x["station_id"] for f, x in net["lifts"].items()}
    out = {}
    for key, x in rep["platform_dirs"].items():
        stop, d = key.split(":")
        out.setdefault(station_of_stop.get(stop), {"platforms": {}, "lifts": {}})["platforms"][key] = {
            "svc_h": x["svc_h"], "months": len(x["months"]), "losses": x["losses"],
            "concurrent_svc_h": x["concurrent_svc_h"]}
    for key, x in rep["reliability_empirical"].items():
        st = station_of_stop.get(key.split(":")[0])
        out.setdefault(st, {"platforms": {}, "lifts": {}}).setdefault("empirical", {})[key] = x["r"]
    for f, x in rep["lifts"].items():
        st = station_of_lift.get(f)
        if st:
            out.setdefault(st, {"platforms": {}, "lifts": {}})["lifts"][f] = x
    total = 0
    meta = {"from": rep["from"], "to": "2026-05"}
    for st, v in out.items():
        if st:
            total += write(OUT / "history" / f"{st}.json", {**meta, **v})
    total += write(OUT / "history" / "lifts.json", {**meta, "lifts": {
        f: {k: x.get(k) for k in ("avail_12m", "outages_12m", "mttr_h", "single_svc_h")} for f, x in rep["lifts"].items()}})
    return total


if __name__ == "__main__":
    sys.exit(main())
