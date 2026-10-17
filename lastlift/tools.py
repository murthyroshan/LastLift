"""The fixed tools the agent (and MCP clients) can call. The LLM never writes Cypher.

Every tool returns the same envelope:
  {ok, tool, summary, data, evidence:{query_ids, graph, ms}, highlight:{nodes, edges}, entities}
`entities` lists every station/lift/platform id the answer may mention (used by grounding).
Wording follows docs/model_rules.md: "loses step-free access in the open-data model", never
"stranded", "safe" or a bare "accessible".
"""
import re
import time

from . import alerts, db, incidents, redundancy, routing, state
from .queries import (Q_COMPLEX_PLATFORMS, Q_COMPLEX_STREETS, Q_LIFT_HISTORY, Q_LIFT_INCIDENT_COUNT, Q_LIFT_INFO,
                      Q_LOST_NOW, Q_NEWLY_LAST, Q_PRIORITY, Q_STATION, Q_STATION_SEARCH)

SCOPES = ("demo", "live", "base")
_FT_SPECIAL = re.compile(r"[-|%*@()\"'~{}\[\]:;!^$+<>=/\\]")


def _envelope(tool, ok, summary, data, query_ids, graph, started, highlight=None, entities=None):
    return {"ok": ok, "tool": tool, "summary": summary, "data": data,
            "evidence": {"query_ids": query_ids, "graph": graph, "ms": round((time.perf_counter() - started) * 1000, 1)},
            "highlight": highlight or {"nodes": [], "edges": []}, "entities": sorted(set(entities or []))}


def _scope_graph(scope):
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")
    if scope == "base":
        return state.graph_name("base")
    if not state.exists(state.graph_name(scope)):
        prepare_scope(scope)
    return state.graph_name(scope)


def prepare_scope(scope):
    """Create/sync a scope graph to its alert set (demo = frozen snapshot, live = latest harvest),
    and write its incident memory."""
    fids = modelled_closed_facilities(alerts.closures_for(scope))
    res = state.ensure_scope(scope, fids)
    res["incidents"] = incidents.sync(scope)
    return res


def modelled_closed_facilities(closures):
    g = db.client().select_graph(state.graph_name("base"))
    fids = sorted({f for c in closures for f in c["facility_ids"]})
    if not fids:
        return []
    rs = g.ro_query("MATCH (l:Node:Lift) WHERE l.facility_id IN $f RETURN collect(DISTINCT l.facility_id)", {"f": fids})
    return sorted(rs.result_set[0][0])


def _fulltext_query(text):
    tokens = [t for t in _FT_SPECIAL.sub(" ", text).split() if t]
    parts = [f"{t}*" for t in tokens] + [f"%{t}%" for t in tokens if len(t) >= 4]
    return " | ".join(parts)


# ----------------------------------------------------------------------------------------------
def resolve_place(query: str, scope: str = "demo"):
    """Find stations (full-text) or a lift by its number."""
    started = time.perf_counter()
    graph = _scope_graph(scope)
    g = db.client().select_graph(graph)
    lifts, stations = [], []
    for num in re.findall(r"\b(\d{3,4})\b", query):
        rs = g.ro_query(Q_LIFT_INFO, {"fid": num}).result_set
        if rs:
            fid, name, short, sid, cx, modelled, closed = rs[0]
            lifts.append({"facility_id": fid, "name": name, "station_id": sid, "modelled": bool(modelled), "closed": closed})
    q = _fulltext_query(re.sub(r"\b\d{3,4}\b", " ", query))
    if q:
        for sid, name, has_pw, has_street, score in g.ro_query(Q_STATION_SEARCH, {"q": q}).result_set:
            stations.append({"station_id": sid, "name": name, "has_pathways": bool(has_pw),
                             "has_accessible_entrance": bool(has_street), "score": round(score, 3)})
    found = bool(lifts or stations)
    summary = ("not in graph" if not found else
               "; ".join([f"lift {l['facility_id']} ({l['name']})" for l in lifts] +
                         [f"{s['name']} ({s['station_id']})" for s in stations[:3]]))
    return _envelope("resolve_place", found, summary, {"lifts": lifts, "stations": stations},
                     ["Q_LIFT_INFO", "Q_STATION_SEARCH"], graph, started,
                     entities=[l["facility_id"] for l in lifts] + [s["station_id"] for s in stations])


def platform_redundancy(station_id: str, scope: str = "demo"):
    """Live, certified board/exit redundancy for every platform at a station."""
    started = time.perf_counter()
    graph = _scope_graph(scope)
    g = db.client().select_graph(graph)
    srs = g.ro_query(Q_STATION, {"sid": station_id}).result_set
    if not srs:
        return _envelope("platform_redundancy", False, "not in graph", {}, ["Q_STATION"], graph, started)
    sid, name, cx, has_pw, has_street = srs[0]
    if not has_pw:
        return _envelope("platform_redundancy", False, f"cannot assess: no pathway topology for {name}",
                         {"station_id": sid, "verdict": "CANNOT_ASSESS"}, ["Q_STATION"], graph, started, entities=[sid])
    streets = g.ro_query(Q_COMPLEX_STREETS, {"cx": cx}).result_set[0][0]
    edges, lift_fac = redundancy.complex_edges(g, cx)
    platforms, hl_edges, ents = [], set(), {sid}
    for stop_id, uids, pname, wb, plat_name in g.ro_query(Q_COMPLEX_PLATFORMS, {"cx": cx}).result_set:
        r = redundancy.platform(g, cx, uids, streets, edges, lift_fac)
        if r is None:
            platforms.append({"stop_id": stop_id, "name": pname, "platform_name": plat_name,
                              "verdict": "no accessible entrance in data"})
            continue
        row = {"stop_id": stop_id, "name": pname, "platform_name": plat_name, "wheelchair_boarding": wb}
        for d in ("board", "exit"):
            x = r[d]
            row[d] = {"k": "at grade" if x.at_grade else x.k, "single_lift": x.k == 1,
                      "last_lift": x.spof_facilities, "cut": x.cut_facilities, "proof": x.proof,
                      "certified": x.outcome, "ms": x.ms}
            for path in x.routes:
                hl_edges.update(path)
            ents.update(x.cut_facilities)
        ents.add(stop_id)
        platforms.append(row)
    k1 = [p for p in platforms if p.get("board", {}).get("k") == 1 or p.get("exit", {}).get("k") == 1]
    summary = f"{name}: {len(platforms)} platforms; {len(k1)} depend on a single lift in the open-data model"
    return _envelope("platform_redundancy", True, summary, {"station_id": sid, "name": name, "platforms": platforms},
                     ["Q_STATION", "Q_COMPLEX_STREETS", "Q_COMPLEX_FLOW_EDGES", "Q_COMPLEX_PLATFORMS", "Q_MAXFLOW"],
                     graph, started, highlight={"nodes": [], "edges": sorted(hl_edges)}, entities=ents)


def current_closures(scope: str = "demo"):
    """Closed lifts, which platforms lose step-free access, and which lifts became the last lift."""
    started = time.perf_counter()
    graph = _scope_graph(scope)
    g = db.client().select_graph(graph)
    closures = alerts.closures_for(scope)
    modelled = set(modelled_closed_facilities(closures))
    items = []
    for c in closures:
        status = "modelled" if set(c["facility_ids"]) & modelled else "cannot_assess"
        items.append({**c, "scope": status})
    lost = [{"stop_id": r[0], "name": r[1], "platform_name": r[2], "station_id": r[3],
             "board": "lost" if r[4] == 0 else "ok", "exit": "lost" if r[5] == 0 else "ok", "departures_day": r[6]}
            for r in g.ro_query(Q_LOST_NOW).result_set]
    newly = [{"facility_id": r[0], "name": r[1], "station_id": r[2], "now_sole_link_for": sorted(r[3])}
             for r in g.ro_query(Q_NEWLY_LAST).result_set]
    summary = (f"{len(closures)} lift alerts ({sum(i['scope'] == 'modelled' for i in items)} modelled, "
               f"{sum(i['scope'] == 'cannot_assess' for i in items)} cannot assess); "
               f"{len(lost)} platforms lose step-free access in the open-data model; "
               f"{len(newly)} lifts are now the last lift for some platform")
    ents = [f for c in closures for f in c["facility_ids"]] + [x["stop_id"] for x in lost] + \
           [x["station_id"] for x in lost] + [n["facility_id"] for n in newly] + [s for c in closures for s in c["stations"]]
    return _envelope("current_closures", True, summary, {"closures": items, "platforms_lost": lost, "newly_last_lift": newly},
                     ["Q_CLOSED_FACILITIES", "Q_LOST_NOW", "Q_NEWLY_LAST"], graph, started, entities=ents)


def what_if_close(facility_ids: list[str], scope: str = "demo"):
    """Simulate closing working lifts on a copy; report platforms that lose access and new last lifts."""
    started = time.perf_counter()
    parent = _scope_graph(scope)
    res = state.what_if(scope, [str(f) for f in facility_ids])
    pg = db.client().select_graph(parent)
    before = {r[0]: r for r in pg.ro_query(Q_LOST_NOW).result_set}
    cg = db.client().select_graph(res["copy"])
    after = {r[0]: r for r in cg.ro_query(Q_LOST_NOW).result_set}
    newly_lost = [{"stop_id": s, "name": r[1], "platform_name": r[2], "station_id": r[3],
                   "board": "lost" if r[4] == 0 else "ok", "exit": "lost" if r[5] == 0 else "ok"}
                  for s, r in after.items() if s not in before]
    parent_last = {(r[0]) for r in pg.ro_query(Q_NEWLY_LAST).result_set}
    new_last = [{"facility_id": r[0], "name": r[1], "station_id": r[2], "now_sole_link_for": sorted(r[3])}
                for r in cg.ro_query(Q_NEWLY_LAST).result_set if r[0] not in parent_last]
    changes = [{"stop_id": s, "board": {"k": v["board"].k, "at_grade": v["board"].at_grade},
                "exit": {"k": v["exit"].k, "at_grade": v["exit"].at_grade}} for s, v in res["recomputed"].items()]
    summary = (f"simulated closing {', '.join(facility_ids)}: {len(newly_lost)} more platforms lose step-free access; "
               f"{len(new_last)} lifts become the last lift (simulation on a copy; live state unchanged)")
    ents = list(facility_ids) + [x["stop_id"] for x in newly_lost] + [n["facility_id"] for n in new_last] + \
        [x["station_id"] for x in newly_lost]
    return _envelope("what_if_close", True, summary,
                     {"copy": res["copy"], "simulated": sorted(facility_ids), "newly_lost": newly_lost,
                      "new_last_lift": new_last, "recomputed": changes},
                     ["Q_CLOSE_LIFTS", "Q_MAXFLOW", "Q_LOST_NOW", "Q_NEWLY_LAST"], res["copy"], started,
                     highlight={"nodes": [f"lift:{f}" for f in facility_ids], "edges": []}, entities=ents)


def step_free_route(from_station: str, to_station: str | None = None, from_platform: str | None = None,
                    scope: str = "demo", alternatives: int = 2):
    """Step-free routes over lifts, walkways and trains, with closures applied. From a station's street
    to another station's street, or from a platform (stop id) out to its station's street. The second
    route avoids every lift the first one uses. Every edge is re-checked in the live graph."""
    started = time.perf_counter()
    graph = _scope_graph(scope)
    to_station = to_station or from_station
    topo = routing.topology(state.graph_name("base"))
    if from_platform:
        src = [u for u, n in topo.nodes.items() if u == from_platform or
               (u.split("#")[0] == from_platform and "Node" in (n.get("labels") or []))]
    else:
        src = [f"street:{from_station}"]
    dst = [f"street:{to_station}"]
    missing = [x for x in src + dst if x not in topo.nodes]
    if not src or missing:
        what = "platform" if from_platform and not src else "station"
        return _envelope("step_free_route", False,
                         f"no accessible entrance in data or unknown {what}: {', '.join(missing) or from_platform}",
                         {"from": src, "to": dst, "routes": []}, ["Q_ROUTE_NODES"], graph, started,
                         entities=[x for x in (from_station, to_station, from_platform) if x])
    res = routing.route(graph, state.graph_name("base"), src, dst, alternatives=alternatives)
    routes = res["routes"]
    ents = [x for x in (from_station, to_station, from_platform) if x]
    if not routes:
        return _envelope("step_free_route", True, "no step-free route in the open-data model",
                         {"from": src, "to": dst, "closed": res["closed"], "routes": []},
                         ["Q_ROUTE_NODES", "Q_ROUTE_EDGES", "Q_CLOSED_FACILITIES"], graph, started, entities=ents)
    best = routes[0]
    summary = (f"{len(routes)} step-free route(s); best ~{best['minutes']} min: " +
               "; ".join(st["text"] for st in best["steps"] if st["kind"] in ("ride", "turnaround", "lift")))
    if len(routes) > 1:
        summary += f". Backup avoiding lifts {', '.join(best['lifts'])}: ~{routes[1]['minutes']} min"
    elif best["lifts"]:
        summary += f". No backup avoiding lifts {', '.join(best['lifts'])}"
    return _envelope("step_free_route", True, summary,
                     {"from": src, "to": dst, "closed": res["closed"], "routes": routes},
                     ["Q_ROUTE_NODES", "Q_ROUTE_EDGES", "Q_CLOSED_FACILITIES", "Q_ROUTE_CHECK_SF", "Q_ROUTE_CHECK_RIDE"], graph, started,
                     highlight={"nodes": best["nodes"], "edges": best["edge_ids"]},
                     entities=ents + [l for r in routes for l in r["lifts"]] +
                     sorted({topo.nodes[n]["station_id"] for r in routes for n in r["nodes"]
                             if topo.nodes.get(n, {}).get("station_id")}))


def repair_priority(scope: str = "demo", limit: int = 10):
    """Rank lifts: closed and cutting access now > newly the last lift > baseline single points, by departures."""
    started = time.perf_counter()
    graph = _scope_graph(scope)
    g = db.client().select_graph(graph)
    lost_stations = {r[3] for r in g.ro_query(Q_LOST_NOW).result_set}
    closed = set(state.closed(graph))
    rows = []
    for fid, name, sid, is_closed, deps, newly, departures, n_inc in g.ro_query(Q_PRIORITY).result_set:
        tier = 2 if newly else 3
        rows.append({"facility_id": fid, "name": name, "station_id": sid, "closed": bool(is_closed),
                     "platform_directions": deps, "newly_last": newly, "departures_day": departures,
                     "incidents": n_inc, "tier": tier})
    for fid in closed:
        if not any(r["facility_id"] == fid for r in rows):
            info = g.ro_query(Q_LIFT_INFO, {"fid": fid}).result_set
            if info and info[0][3] in lost_stations:
                n_inc = g.ro_query(Q_LIFT_INCIDENT_COUNT, {"fid": fid}).result_set[0][0]
                rows.append({"facility_id": fid, "name": info[0][1], "station_id": info[0][3], "closed": True,
                             "platform_directions": 0, "newly_last": 0, "departures_day": 0, "incidents": n_inc,
                             "tier": 1})
    rank(rows)
    labels = {1: "repair now (closed, platforms lose access)", 2: "protect (newly the last lift)",
              3: "structural single point of failure"}
    for r in rows:
        r["tier_label"] = labels[r["tier"]]
    top = rows[:limit]
    summary = "; ".join(f"{r['facility_id']} ({r['tier_label']})" for r in top[:3]) or "no lift dependencies"
    return _envelope("repair_priority", True, summary, {"ranked": top},
                     ["Q_PRIORITY", "Q_LOST_NOW", "Q_LIFT_INFO", "Q_LIFT_INCIDENT_COUNT"],
                     graph, started, entities=[r["facility_id"] for r in top] + [r["station_id"] for r in top])


def rank(rows):
    """Lexicographic, reasons shown: tier, then newly-last count, then scheduled departures, then how
    many closures of this lift are on record (incident memory), then facility id."""
    rows.sort(key=lambda r: (r["tier"], -r["newly_last"], -r["departures_day"], -r.get("incidents", 0),
                             r["facility_id"]))
    return rows


def lift_history(facility_id: str, scope: str = "demo"):
    """Closures of this lift on record (incident memory in the graph, from MBTA alerts the collector saw)."""
    started = time.perf_counter()
    graph = _scope_graph(scope)
    g = db.client().select_graph(graph)
    keys = ("alert_id", "effect", "header", "started", "first_seen", "last_seen", "ongoing", "ended_by", "versions")
    events = [dict(zip(keys, r)) for r in g.ro_query(Q_LIFT_HISTORY, {"fid": str(facility_id)}).result_set]
    since = alerts.activity().get("first_poll")
    ongoing = sum(1 for e in events if e["ongoing"])
    began = f" since collection began {since[:10]}" if since else ""
    summary = (f"lift {facility_id}: {len(events)} closure alert(s) on record ({ongoing} ongoing){began}"
               if events else f"lift {facility_id}: no closures on record{began}")
    return _envelope("lift_history", True, summary,
                     {"facility_id": facility_id, "incidents": events, "collection_began": since},
                     ["Q_LIFT_HISTORY"], graph, started, entities=[facility_id])


def draft_action(facility_id: str, scope: str = "demo"):
    """Draft (never file) a repair-priority ticket for a lift, citing graph evidence."""
    started = time.perf_counter()
    pr = repair_priority(scope, limit=200)["data"]["ranked"]
    row = next((r for r in pr if r["facility_id"] == facility_id), None)
    hist = lift_history(facility_id, scope)["data"]["incidents"]
    if row is None:
        return _envelope("draft_action", False, f"lift {facility_id} has no platform depending on it alone",
                         {}, ["Q_PRIORITY"], state.graph_name(scope), started, entities=[facility_id])
    title = f"[LastLift] Lift {facility_id} ({row['name']}): {row['tier_label']}"
    body = "\n".join([
        f"**Lift:** {facility_id} ({row['name']})",
        f"**Priority tier:** {row['tier']} ({row['tier_label']})",
        f"**Platform-directions with no other step-free route:** {row['platform_directions']}",
        f"**Scheduled departures affected (day):** {row['departures_day']}",
        f"**Closures on record (incident memory):** {len(hist)}",
        "",
        "_Draft generated from the open-data model (unofficial decision support). Not filed automatically._",
    ])
    return _envelope("draft_action", True, f"draft ticket for lift {facility_id}", {"title": title, "body": body,
                     "filed": False}, ["Q_PRIORITY"], state.graph_name(scope), started, entities=[facility_id])


REGISTRY = {f.__name__: f for f in (resolve_place, current_closures, platform_redundancy, what_if_close,
                                    step_free_route, repair_priority, lift_history, draft_action)}
