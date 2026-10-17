"""The Step-Free Atlas (MS5): for every agency that publishes GTFS-Pathways, how many platforms depend on a single
lift. Computed with LastLift's rules from the agency's published files, and re-checked in FalkorDB.

    python scripts/atlas_sweep.py                  # data/raw/atlas/<id>/ -> data/atlas.json, claims (atlas_*)
    python scripts/atlas_sweep.py mdb-437 --no-falkordb   # one feed, Python only (a dry run; writes nothing)

Generic rules (no agency-specific overrides): walkways, travelators and fare gates are step-free (gates assumed
passable); stairs and escalators are not; every elevator pathway belongs to a lift unit (its facility_id where the
feed has facilities.txt, otherwise the connected group of elevator pathways), node-split with capacity 1, so a max-flow
counts lift-disjoint routes. Generic nodes and boarding areas the feed marks wheelchair_boarding = 2 are left out;
a platform includes its boarding areas. Sources: the station's entrances marked wheelchair_boarding = 1; where a station's
entrances carry no flag at all, those not marked 2 are used and the agency's readiness grade says so. Board k = flow
street -> platform, exit k = platform -> street, per parent station. Every lift-dependent platform-direction is
re-checked with FalkorDB's certified max-flow, one station at a time in a temporary graph that is deleted after.
Results describe each agency's published data model, not its stations.
"""
import csv
import io
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift import db, redundancy  # noqa: E402
from lastlift.config import settings  # noqa: E402
from lastlift.flow import exact_maxflow  # noqa: E402

RAW = ROOT / "data" / "raw" / "atlas"
BIG = 1_000_000
STEP_FREE = {"1": "walk", "3": "walk", "6": "gate", "7": "gate"}


def rd(path):
    if not path.is_file():
        return []
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig", errors="replace"))))


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def build(feed_dir):
    stops = {s["stop_id"]: s for s in rd(feed_dir / "stops.txt")}
    paths = rd(feed_dir / "pathways.txt")

    def station(sid):
        seen = set()
        while sid in stops and stops[sid].get("location_type") not in ("1",) and stops[sid].get("parent_station") \
                and sid not in seen:
            seen.add(sid)
            sid = stops[sid]["parent_station"]
        return sid
    has_fac = any(p.get("facility_id") for p in paths)
    uf = UF()
    lifts = [p for p in paths if p.get("pathway_mode") == "5"]
    for p in lifts:
        if not (has_fac and p.get("facility_id")):
            uf.union(p["from_stop_id"], p["to_stop_id"])
    edges = defaultdict(list)                    # station -> [(eid, u, v, cap)]
    lift_fac = defaultdict(dict)                 # station -> {lift edge id: unit}
    n = 0
    blocked = {sid for sid, s in stops.items() if (s.get("location_type") or "0") in ("3", "4")
               and s.get("wheelchair_boarding") == "2"}
    for p in paths:
        mode = p.get("pathway_mode")
        a, b = p["from_stop_id"], p["to_stop_id"]
        if a in blocked or b in blocked:
            continue
        st = station(a)
        pairs = [(a, b)] + ([(b, a)] if p.get("is_bidirectional") == "1" else [])
        for u, v in pairs:
            if mode in STEP_FREE:
                n += 1
                edges[st].append((f"e{n}", u, v, BIG))
            elif mode == "5":
                unit = p["facility_id"] if has_fac and p.get("facility_id") else f"u{uf.find(a)}"
                key = f"lift:{unit}"
                n += 3
                edges[st] += [(f"e{n - 2}", u, key, BIG), (f"L{n - 1}", key, f"{key}:out", 1),
                              (f"e{n}", f"{key}:out", v, BIG)]
                lift_fac[st][f"L{n - 1}"] = unit
    # collapse duplicate lift edges of a unit (one capacity-1 edge per unit)
    for st, es in edges.items():
        seen, out = set(), []
        for e in es:
            k = (e[1], e[2]) if e[0].startswith("L") else (e[0],)
            if e[0].startswith("L") and k in seen:
                continue
            seen.add(k)
            out.append(e)
        edges[st] = out
        kept = {e[0] for e in out}
        lift_fac[st] = {e: u for e, u in lift_fac[st].items() if e in kept}
    in_paths = {x for p in paths for x in (p["from_stop_id"], p["to_stop_id"])}
    stations = defaultdict(lambda: {"entrances": [], "platforms": defaultdict(list), "flags": []})
    for sid, s in stops.items():
        if sid not in in_paths:
            continue
        st = station(sid)
        lt = s.get("location_type") or "0"
        if lt == "2":
            stations[st]["entrances"].append(sid)
            stations[st]["flags"].append(s.get("wheelchair_boarding") or "")
        elif lt == "0":
            stations[st]["platforms"][sid].append(sid)
        elif lt == "4" and s.get("parent_station") in stops:      # a boarding area is part of its platform
            stations[st]["platforms"][s["parent_station"]].append(sid)
    return stops, paths, edges, lift_fac, stations, has_fac


def merge(edges):
    """One edge per (from, to) pair with the capacities summed (capped at BIG): FalkorDB's max-flow takes no parallel
    edges, and both solvers must see the same network. Lift edges are already unique per lift unit."""
    out = {}
    for eid, u, v, cap in edges:
        if (u, v) in out:
            e = out[(u, v)]
            out[(u, v)] = (e[0], u, v, min(BIG, e[3] + cap))
        else:
            out[(u, v)] = (eid, u, v, cap)
    return list(out.values())


def sweep_agency(feed_dir, check):
    stops, paths, edges, lift_fac, stations, has_fac = build(feed_dir)
    c = Counter()
    flagless = 0
    top = []
    falkor = Counter()
    for st, s in stations.items():
        if not s["platforms"]:
            continue
        flags = s["flags"]
        if flags and all(f in ("", "0") for f in flags):
            flagless += 1
            src = [e for e, f in zip(s["entrances"], flags) if f != "2"]
        else:
            src = [e for e, f in zip(s["entrances"], flags) if f == "1"]
        es = edges.get(st, [])
        adj = merge(es + [(f"S{i}", "STREET", e, BIG) for i, e in enumerate(src)]
                    + [(f"T{i}", e, "STREET", BIG) for i, e in enumerate(src)])
        lifts_here = set(lift_fac.get(st, {}).values())
        station_k1 = 0
        before = c["at_grade"]
        for p, uids in sorted(s["platforms"].items()):
            c["platforms"] += 1
            if (stops[p].get("wheelchair_boarding") or "") == "2":
                c["marked_not_accessible"] += 1
                continue
            if not src:
                c["no_accessible_entrance"] += 1
                continue
            ks = []
            for d in ("board", "exit"):
                a, b = (["STREET"], uids) if d == "board" else (uids, ["STREET"])
                v, _ = exact_maxflow(adj, a, b)
                k = None if v >= BIG else int(v)
                ks.append(k)
                if check and k is not None and k > 0:
                    falkor["checked"] += 1
                    falkor["equal" if check(st, adj, lift_fac.get(st, {}), a, b) == k else "different"] += 1
            finite = [k for k in ks if k is not None]
            if not finite:
                c["at_grade"] += 1
            elif min(finite) == 0:
                c["no_route"] += 1
            elif min(finite) == 1:
                c["single_lift"] += 1
                station_k1 += 1
            else:
                c["two_plus"] += 1
        if lifts_here:
            c["at_grade_beside_lifts"] += c["at_grade"] - before
        if station_k1:
            top.append({"station": stops.get(st, {}).get("stop_name", st), "single_lift_platforms": station_k1,
                        "lifts": len(lifts_here)})
    units = {u for d in lift_fac.values() for u in d.values()}
    dep = c["single_lift"] + c["two_plus"] + c["no_route"]
    grade = ("C" if not units else "A" if has_fac and flagless == 0 else "B")
    return {"platforms": c["platforms"], "at_grade": c["at_grade"], "single_lift": c["single_lift"],
            "two_plus": c["two_plus"], "no_route": c["no_route"], "no_accessible_entrance": c["no_accessible_entrance"],
            "marked_not_accessible": c["marked_not_accessible"],
            "at_grade_beside_lifts": c["at_grade_beside_lifts"], "lift_units": len(units),
            "elevator_pathways": sum(1 for p in paths if p.get("pathway_mode") == "5"), "facility_ids": has_fac,
            "stations_without_entrance_flags": flagless, "lift_dependent": dep,
            "single_lift_share": round(c["single_lift"] / dep, 3) if dep else None, "readiness": grade,
            "assessable": bool(units), "falkordb": dict(falkor),
            "top_stations": sorted(top, key=lambda x: (-x["single_lift_platforms"], x["station"]))[:5]}


def falkordb_checker():
    """k for one platform-direction, from FalkorDB's certified max-flow on a one-station temporary graph."""
    name = f"{settings.graph_prefix}_atlas_tmp_{os.getpid()}"
    g = db.client().select_graph(name)
    loaded = {"st": None}

    def check(st, adj, lift_fac, sources, sinks):
        if loaded["st"] != st:
            g.query("MATCH (n) DETACH DELETE n") if loaded["st"] is not None else None
            nodes = sorted({x for e in adj for x in e[1:3]})
            g.query("UNWIND $n AS u CREATE (:Node {uid:u})", {"n": nodes})
            if loaded["st"] is None:
                g.query("CREATE INDEX FOR (n:Node) ON (n.uid)")
            for i in range(0, len(adj), 1000):
                g.query("UNWIND $e AS e MATCH (a:Node {uid:e[1]}) MATCH (b:Node {uid:e[2]}) "
                        "CREATE (a)-[:SF {eid:e[0], cap:e[3]}]->(b)", {"e": [list(e) for e in adj[i:i + 1000]]})
            loaded["st"] = st
        r = redundancy.direction(g, adj, lift_fac, sources, sinks)
        return 0 if r.k is None and not r.at_grade else r.k
    return check, lambda: db.client().select_graph(name).delete() if name in db.client().list_graphs() else None


LICENCES = ROOT / "data" / "atlas_licences.json"     # the author's licence check: id -> include | exclude | unchecked


def write_public(rows):
    """web/public/m/atlas.json: named rows only for agencies whose licence the author marked "include" (MBTA, our own
    source, is included); every other agency is counted in the aggregates without its name."""
    gate = json.loads(LICENCES.read_text(encoding="utf-8")) if LICENCES.is_file() else {}
    keep = ("platforms", "single_lift", "two_plus", "at_grade", "no_route", "lift_dependent", "single_lift_share",
            "lift_units", "readiness", "assessable", "falkordb", "stations_without_entrance_flags", "facility_ids")
    named = [{"id": r["id"], "provider": r["provider"], "country": r["country"], "license": r["license"],
              **{k: r[k] for k in keep}, "top_stations": r["top_stations"]}
             for r in rows if gate.get(r["id"]) == "include"]
    assessed = [r for r in rows if r["assessable"]]
    agg = {"feeds": len(rows), "assessable": len(assessed), "named": len(named),
           "platforms": sum(r["platforms"] for r in assessed),
           "lift_dependent": sum(r["lift_dependent"] for r in assessed),
           "single_lift": sum(r["single_lift"] for r in assessed),
           "falkordb_checked": sum(r["falkordb"].get("checked", 0) for r in rows),
           "falkordb_equal": sum(r["falkordb"].get("equal", 0) for r in rows),
           "grades": {g: sum(1 for r in rows if r["readiness"] == g) for g in ("A", "B", "C")},
           "shares": sorted(r["single_lift_share"] for r in assessed if r["single_lift_share"] is not None)}
    out = ROOT / "web" / "public" / "m" / "atlas.json"
    out.write_text(json.dumps({"aggregate": agg, "agencies": named}, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    sources = json.loads((ROOT / "data" / "atlas_sources.json").read_text(encoding="utf-8"))
    if "--no-falkordb" in sys.argv:
        check, cleanup = None, lambda: None
    else:
        check, cleanup = falkordb_checker()
    rows = []
    try:
        for s in sources:
            if s.get("error") or (only and s["id"] not in only):
                continue
            r = sweep_agency(RAW / s["id"], check)
            rows.append({"id": s["id"], "provider": s["provider"], "country": s["country"], "license": s["license"],
                         **r})
            print(s["id"], s["provider"][:32], {k: r[k] for k in ("platforms", "single_lift", "two_plus", "at_grade",
                                                                 "lift_units", "readiness", "falkordb")}, flush=True)
    finally:
        cleanup()
    if only or check is None:
        return 0
    (ROOT / "data" / "atlas.json").write_text(json.dumps({"agencies": rows}, indent=1, sort_keys=True,
                                                         ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    write_public(rows)
    claims_path = ROOT / "claims.json"
    claims = {k: v for k, v in json.loads(claims_path.read_text(encoding="utf-8")).items() if not k.startswith("atlas_")}
    claims.update({"atlas_feeds": len(rows), "atlas_assessable": sum(1 for r in rows if r["assessable"]),
                   "atlas_falkordb_checked": sum(r["falkordb"].get("checked", 0) for r in rows),
                   "atlas_falkordb_equal": sum(r["falkordb"].get("equal", 0) for r in rows)})
    claims_path.write_text(json.dumps(claims, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "web" / "public" / "claims.json").write_bytes(claims_path.read_bytes())
    return 0


if __name__ == "__main__":
    sys.exit(main())
