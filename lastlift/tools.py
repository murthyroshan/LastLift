"""The fixed tools the agent (and MCP clients) can call. The LLM never writes Cypher.

Every tool returns the same envelope:
  {ok, tool, summary, data, evidence:{query_ids, graph, ms}, highlight:{nodes, edges}, entities}
`entities` lists every station/lift/platform id the answer may mention (used by grounding).
Wording follows docs/model_rules.md: "loses step-free access in the open-data model", never
"stranded", "safe" or a bare "accessible".
"""
import re
import time
from typing import Annotated

from pydantic import Field

from . import alerts, db, incidents, redundancy, routing, state
from .queries import (Q_CLOSED_AT_COMPLEX, Q_COMPLEX_PLATFORMS, Q_STATION_PLATFORMS, Q_COMPLEX_STREETS, Q_LIFT_HISTORY, Q_LIFT_INCIDENT_COUNT, Q_LIFT_INFO,
                      Q_LOST_NOW, Q_NEWLY_LAST, Q_PRIORITY, Q_STATION, Q_STATION_SEARCH)

SCOPES = ("demo", "live", "base")
_FT_TOKEN = re.compile(r"[A-Za-z0-9]+")
# Question words never name a station; dropping them keeps the full-text query small and on-topic.
_FT_STOP = {"a", "an", "and", "are", "at", "be", "can", "do", "does", "for", "from", "get", "how", "i", "in", "is",
            "it", "lift", "lifts", "elevator", "elevators", "me", "my", "now", "of", "on", "onto", "or", "right",
            "step", "free", "the", "to", "today", "what", "when", "where", "which", "who", "will", "with"}


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
    """Letters and digits only: punctuation such as '?' is query syntax for the full-text engine."""
    tokens = [t for t in _FT_TOKEN.findall(text) if t.lower() not in _FT_STOP]
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
    base_k = {r[0]: {"board": r[6], "exit": r[7]} for r in g.ro_query(Q_STATION_PLATFORMS, {"cx": cx}).result_set}
    closed_here = sorted(g.ro_query(Q_CLOSED_AT_COMPLEX, {"cx": cx}).result_set[0][0])
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
            kb = base_k.get(stop_id, {}).get(d)
            row[d] = {"k": "at grade" if x.at_grade else x.k, "k_before_closures": kb, "single_lift": x.k == 1,
                      "last_lift": x.spof_facilities, "cut": x.cut_facilities, "proof": x.proof,
                      "certified": x.outcome, "ms": x.ms}
            for path in x.routes:
                hl_edges.update(path)
            ents.update(x.cut_facilities)
        ents.add(stop_id)
        platforms.append(row)
    def label(p):
        return " ".join(x for x in (p.get("platform_name"), "platform") if x) if p.get("platform_name") else p["stop_id"]

    lost = [p for p in platforms if 0 in (p.get("board", {}).get("k"), p.get("exit", {}).get("k"))]
    k1 = [p for p in platforms if p not in lost and 1 in (p.get("board", {}).get("k"), p.get("exit", {}).get("k"))]
    parts = [f"{name}: {len(platforms)} platform{'s' if len(platforms) != 1 else ''}"]
    if lost:
        parts.append(f"{len(lost)} lose{'s' if len(lost) == 1 else ''} step-free access now in the open-data model "
                     f"({', '.join(label(p) for p in lost)})")
    def dep(p):
        lifts = p.get("board", {}).get("last_lift") or p.get("exit", {}).get("last_lift") or ["?"]
        before = [p.get(d, {}).get("k_before_closures") for d in ("board", "exit")]
        newly = any(isinstance(k, int) and k >= 2 for k in before)
        if not newly:
            return f"{label(p)}: lift {'/'.join(lifts)}"
        cause = (f"with lift(s) {', '.join(closed_here)} closed here, its other lift routes are gone"
                 if closed_here else "its other lift routes are cut by current closures")
        return f"{label(p)}: lift {'/'.join(lifts)} is newly the only lift ({cause})"
    parts.append(f"{len(k1)} depend{'s' if len(k1) == 1 else ''} on a single lift"
                 + (f" ({'; '.join(dep(p) for p in k1[:4])})" if k1 else ""))
    if closed_here:
        parts.append(f"lift(s) closed here now: {', '.join(closed_here)}")
    summary = "; ".join(parts)
    return _envelope("platform_redundancy", True, summary, {"station_id": sid, "name": name, "platforms": platforms,
                                                           "closed_here": closed_here},
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
               f"{len(newly)} lifts are now the last lift for some platform"
               + (": " + ", ".join(f"{n['facility_id']} ({n['name'].split(' Elevator')[0]})" for n in newly)
                  if newly else ""))
    ents = [f for c in closures for f in c["facility_ids"]] + [x["stop_id"] for x in lost] + \
           [x["station_id"] for x in lost] + [n["facility_id"] for n in newly] + [s for c in closures for s in c["stations"]]
    return _envelope("current_closures", True, summary, {"closures": items, "platforms_lost": lost, "newly_last_lift": newly},
                     ["Q_CLOSED_FACILITIES", "Q_LOST_NOW", "Q_NEWLY_LAST"], graph, started, entities=ents)


def what_if_close(facility_ids: list[str], scope: str = "demo"):
    """Simulate closing working lifts on a copy; report platforms that lose access and new last lifts."""
    started = time.perf_counter()
    parent = _scope_graph(scope)
    asked = [str(f) for f in facility_ids]
    modelled = set(modelled_closed_facilities([{"facility_ids": asked}]))
    unknown = [f for f in asked if f not in modelled]
    if unknown:  # never simulate a lift the model does not contain: that would read as "no effect"
        return _envelope("what_if_close", False,
                         f"cannot assess: lift(s) {', '.join(unknown)} not in the step-free model "
                         "(no published station layout, or not a lift)",
                         {"simulated": [], "cannot_assess": unknown}, ["Q_MODELLED_LIFTS"], parent, started,
                         entities=asked)
    already = sorted(set(asked) & set(state.closed(parent)))
    if already and set(already) == set(asked):    # nothing to simulate: say so instead of "0 more platforms"
        return _envelope("what_if_close", True,
                         f"lift(s) {', '.join(already)} already closed in this scope: nothing to simulate; "
                         "use current_closures or platform_redundancy for their effect now",
                         {"simulated": [], "already_closed": already}, ["Q_CLOSED_FACILITIES"], parent, started,
                         entities=asked)
    res = state.what_if(scope, asked)
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


def _station_id(g, name_or_id):
    """A station id (place-...) as given, or the station whose name best matches the text."""
    if not name_or_id or str(name_or_id).startswith("place-"):
        return name_or_id
    q = _fulltext_query(str(name_or_id))
    rows = g.ro_query(Q_STATION_SEARCH, {"q": q}).result_set if q else []
    exact = [r for r in rows if r[1].lower() == str(name_or_id).lower()]
    return (exact or rows or [[name_or_id]])[0][0]


def _platform_stop(g, station_id, platform):
    """A platform stop id as given, or the station platform whose name contains the text (e.g. 'Wonderland')."""
    if not platform or not station_id:
        return platform
    srs = g.ro_query(Q_STATION, {"sid": station_id}).result_set
    if not srs:
        return platform
    rows = g.ro_query(Q_COMPLEX_PLATFORMS, {"cx": srs[0][2]}).result_set
    if any(r[0] == str(platform) for r in rows):
        return str(platform)
    text = str(platform).lower()
    for stop_id, _uids, pname, _wb, plat_name in rows:
        label = " ".join(x for x in (plat_name, pname) if x).lower()
        if text in label or (plat_name and plat_name.lower().split(" ")[0] in text):
            return stop_id
    return platform


StationArg = Annotated[str, Field(description="Station id from resolve_place (e.g. place-rbmnl) or a station name")]
PlatformArg = Annotated[str | None, Field(description="Platform stop_id from platform_redundancy (e.g. 70058) or a "
                                                      "platform name (e.g. 'Wonderland'); needs from_station")]


def step_free_route(from_station: StationArg, to_station: StationArg | None = None,
                    from_platform: PlatformArg = None, to_platform: PlatformArg = None,
                    also_closed: Annotated[list[str] | None, Field(
                        description="Lift numbers to treat as closed too (what-if reroute; nothing is changed)")] = None,
                    scope: str = "demo", alternatives: int = 2):
    """Step-free routes over lifts, walkways and trains, with closures applied. From a station's street
    (or from a platform: exiting) to a station's street (or onto a platform: boarding). Give the platform
    to answer 'can I board / get off at ...'. The second route avoids every lift the first one uses.
    Every edge is re-checked in the live graph."""
    started = time.perf_counter()
    graph = _scope_graph(scope)
    g = db.client().select_graph(graph)
    from_station = _station_id(g, from_station)
    to_station = _station_id(g, to_station) or from_station
    from_platform = _platform_stop(g, from_station, from_platform)
    to_platform = _platform_stop(g, to_station, to_platform)
    topo = routing.topology(state.graph_name("base"))

    def platform_uids(stop):
        return [u for u, n in topo.nodes.items()
                if u == stop or (u.split("#")[0] == stop and "Node" in (n.get("labels") or []))]

    src = platform_uids(from_platform) if from_platform else [f"street:{from_station}"]
    dst = platform_uids(to_platform) if to_platform else [f"street:{to_station}"]
    missing = [x for x in src + dst if x not in topo.nodes]
    if not src or not dst or missing:
        what = "platform" if (from_platform and not src) or (to_platform and not dst) else "station"
        reason = ("no step-free entrance in the station layout data (or unknown station)" if what == "station"
                  else "unknown platform")
        return _envelope("step_free_route", False,
                         f"cannot route: {reason}: {', '.join(missing) or from_platform or to_platform}",
                         {"from": src, "to": dst, "routes": []}, ["Q_ROUTE_NODES"], graph, started,
                         entities=[x for x in (from_station, to_station, from_platform, to_platform) if x])
    res = routing.route(graph, state.graph_name("base"), src, dst, alternatives=alternatives,
                        also_closed=also_closed or ())
    routes = res["routes"]
    ents = [x for x in (from_station, to_station, from_platform, to_platform) if x]
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
    labels = {1: "repair now (closed, platforms lose access)",
              2: "protect (working, and already the last lift for some platforms because of current closures)",
              3: "structural single point of failure (the only lift even when all others work)"}
    for r in rows:
        r["tier_label"] = labels[r["tier"]]
    top = rows[:limit]
    summary = "; ".join(f"lift {r['facility_id']} ({r['name']}): {r['tier_label']}" for r in top[:3]) or \
        "no lift dependencies"
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
