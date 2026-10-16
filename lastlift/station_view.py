"""The station graph contract: one station complex, contracted for drawing (the SVG x-ray).

    GET /v1/stations/{station_id}/graph?dir=board|exit&scope=demo&scenario=<what-if copy>

Contraction rules (ids are stable across calls and closures):
  * each maximal cluster of Generic nodes joined by step-free walkways -> one `area`
  * all fare gates between the same two areas -> one `gate`
  * Lift + LiftOut -> one `lift` node; the edges into and out of it carry kind `lift`
  * a landing (a one-node area whose only walkway leads to a single platform or entrance) is absorbed
    into that platform or entrance
  * streets, entrances and platforms are kept as they are
`band` is the inferred level: the fewest vertical connectors (lifts, stairs, escalators) between the
street and the node, by 0-1 BFS. MBTA publishes no level data, so levels are inferred and unsigned
(a band says how many level changes away, not up or down). `rank` is the hop layer from the street.
"""
import hashlib
import time
from collections import deque

from . import db, redundancy, state
from .queries import (Q_COMPLEX_STREETS, Q_META, Q_STATION, Q_STATION_EDGES,
                      Q_STATION_NODES, Q_STATION_PLATFORMS, Q_STATION_UNMODELLED_LIFTS)

SCHEMA_VERSION = 1


def _kind(labels):
    for label, kind in (("Street", "street"), ("Entrance", "entrance"), ("Platform", "platform"),
                        ("LiftOut", "lift"), ("Lift", "lift"), ("Generic", "area")):
        if label in labels:
            return kind
    return "area"


def contract(nodes: list[dict], edges: list[dict]):
    """nodes: {uid, labels, name, platform_name, facility_id, unit, closed, stop_id, wb}
    edges: {eid, a, b, type (SF|SF_CLOSED|STEP), kind, facility_id, pathway_ids}
    Returns (contracted nodes by id, contracted edges by id, raw eid -> contracted edge id)."""
    by_uid = {n["uid"]: n for n in nodes}
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    generic = {u for u, n in by_uid.items() if "Generic" in n["labels"]}
    for e in edges:
        if e["type"] == "SF" and e["kind"] == "walk" and e["a"] in generic and e["b"] in generic:
            ra, rb = find(e["a"]), find(e["b"])
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)        # the smallest uid names the cluster: stable

    clusters = {}
    for u in generic:
        clusters.setdefault(find(u), []).append(u)
    walk_nb = {}
    for e in edges:
        if e["type"] == "SF" and e["kind"] == "walk":
            walk_nb.setdefault(e["a"], set()).add(e["b"])
            walk_nb.setdefault(e["b"], set()).add(e["a"])
    absorb = {}
    for root, members in clusters.items():
        if len(members) == 1:
            ends = {x for x in walk_nb.get(members[0], ()) if x in by_uid and
                    {"Platform", "Entrance"} & set(by_uid[x]["labels"])}
            if len(ends) == 1 and walk_nb.get(members[0], set()) <= ends:
                absorb[members[0]] = ends.pop()

    def cid(uid):
        n = by_uid.get(uid)
        if n is None:
            return None
        if uid in absorb:
            return absorb[uid]
        if uid in generic:
            return f"area:{find(uid)}"
        if "Lift" in n["labels"] or "LiftOut" in n["labels"]:
            return f"lift:{n['unit']}"
        return uid

    cnodes = {}
    for uid, n in by_uid.items():
        c = cid(uid)
        if uid in absorb:
            continue                                     # added to its platform/entrance below
        k = _kind(n["labels"])
        node = cnodes.setdefault(c, {"id": c, "kind": k, "label": n.get("name") or uid, "members": []})
        node["members"].append(uid)
        if k == "lift" and "Lift" in n["labels"]:
            node.update(label=n.get("name") or uid, facility_id=n.get("facility_id"),
                        status="closed" if n.get("closed") else "open")
        if k == "platform":
            node.update(stop_id=n.get("stop_id"), wb=n.get("wb"),
                        label=" ".join(x for x in (n.get("name"), n.get("platform_name")) if x))
    for uid, target in absorb.items():
        cnodes[target]["members"].append(uid)
    for node in cnodes.values():
        if node["kind"] == "area" and len(node["members"]) > 1:
            node["label"] = f"{by_uid[node['members'][0]].get('name') or 'area'} (+{len(node['members']) - 1})"

    cedges, raw_map = {}, {}

    def add(src, dst, kind, e, step_free):
        eid = f"{kind}:{src}>{dst}"
        ce = cedges.setdefault(eid, {"id": eid, "source": src, "target": dst, "kind": kind, "pathway_ids": [],
                                     "step_free": step_free, "raw": []})
        if e.get("facility_id"):
            ce["facility_id"] = e["facility_id"]
        ce["pathway_ids"] = sorted(set(ce["pathway_ids"]) | set(e.get("pathway_ids") or []))
        ce["raw"].append(e["eid"])
        raw_map.setdefault(e["eid"], []).append(eid)

    for e in edges:
        a, b = cid(e["a"]), cid(e["b"])
        if a is None or b is None or a == b:
            if a is not None and a == b and e["kind"] == "lift":
                raw_map[e["eid"]] = []                   # the lift's own edge lives inside the lift node
            continue
        if e["type"] == "STEP":
            add(a, b, "step", e, False)
        elif e["kind"] == "gate":
            g = "gate:" + "|".join(sorted((a, b)))
            cnodes.setdefault(g, {"id": g, "kind": "gate", "label": "fare gates", "members": []})
            add(a, g, "gate", e, True)
            add(g, b, "gate", e, True)
        else:
            lift_side = a if cnodes[a]["kind"] == "lift" else b if cnodes[b]["kind"] == "lift" else None
            if lift_side:
                e = {**e, "facility_id": cnodes[lift_side].get("facility_id")}
            add(a, b, "lift" if lift_side else "walk", e, e["type"] == "SF" or bool(lift_side))
    return cnodes, cedges, raw_map


def layers(cnodes, cedges):
    """rank = undirected hop distance from the street; band = fewest level changes from the street
    (0-1 BFS: leaving a lift or taking stairs/an escalator costs 1, everything else 0)."""
    adj = {n: [] for n in cnodes}
    for e in cedges.values():
        w = 1 if e["kind"] == "step" else 0
        adj[e["source"]].append((e["target"], w))
        adj[e["target"]].append((e["source"], w))
    roots = [n for n, x in cnodes.items() if x["kind"] == "street"] or \
            [n for n, x in cnodes.items() if x["kind"] == "entrance"]
    rank = {r: 0 for r in roots}
    q = deque(roots)
    while q:
        u = q.popleft()
        for v, _ in adj[u]:
            if v not in rank:
                rank[v] = rank[u] + 1
                q.append(v)
    band = {r: 0 for r in roots}
    dq = deque(roots)
    while dq:
        u = dq.popleft()
        for v, step in adj[u]:
            w = 1 if step or cnodes[u]["kind"] == "lift" else 0
            if band[u] + w < band.get(v, 1 << 30):
                band[v] = band[u] + w
                (dq.appendleft if w == 0 else dq.append)(v)
    return rank, band


def _verdict(p):
    if p.get("no_accessible_entrance"):
        return "no accessible entrance in data"
    lost = [d for d in ("board", "exit") if p.get(f"k_{d}") == 0 and
            ((p.get(f"k_{d}_base") or 0) > 0 or p.get(f"at_grade_{d}"))]
    if lost:
        return "loses step-free " + " and ".join("boarding" if d == "board" else "exit" for d in lost) + \
            " in the open-data model"
    if 1 in (p.get("k_board"), p.get("k_exit")):
        return "depends on a single lift"
    if p.get("at_grade_board_now") and p.get("at_grade_exit_now"):
        return "at grade (no lift needed)"
    return "two or more lift-disjoint routes"


def view(station_id: str, direction: str = "board", scope: str = "demo", scenario: str | None = None):
    """Build the contract for one station. `scenario` is a what-if copy name returned by what_if_close."""
    started = time.perf_counter()
    if direction not in ("board", "exit"):
        raise ValueError("dir must be board or exit")
    parent_graph = state.graph_name(scope)
    graph = parent_graph
    if scenario:
        if not scenario.startswith(state.graph_name("wi_")) or not state.exists(scenario):
            raise LookupError(f"unknown scenario {scenario}")
        graph = scenario
    g = db.client().select_graph(graph)
    srs = g.ro_query(Q_STATION, {"sid": station_id}).result_set
    if not srs:
        raise LookupError(f"station {station_id} not in graph")
    sid, name, cx, has_pw, has_street = srs[0]
    meta = g.ro_query(Q_META).result_set
    closed = state.closed(graph)
    parent_closed = set(state.closed(parent_graph)) if scenario else set(closed)

    nodes = [{"uid": r[0], "labels": r[1], "name": r[2], "platform_name": r[3], "facility_id": r[4], "unit": r[5],
              "closed": r[6], "stop_id": r[7], "wb": r[8]} for r in g.ro_query(Q_STATION_NODES, {"cx": cx}).result_set]
    edges = [{"eid": r[0], "a": r[1], "b": r[2], "type": r[3], "kind": r[4], "facility_id": r[5], "pathway_ids": r[6]}
             for r in g.ro_query(Q_STATION_EDGES, {"cx": cx}).result_set]
    cnodes, cedges, raw_map = contract(nodes, edges)
    rank, band = layers(cnodes, cedges)

    platforms, routes, receipt_ms = [], [], 0.0
    plat_rows = g.ro_query(Q_STATION_PLATFORMS, {"cx": cx}).result_set
    streets = g.ro_query(Q_COMPLEX_STREETS, {"cx": cx}).result_set[0][0]
    flow_edges, lift_fac = redundancy.complex_edges(g, cx)
    last_lift = {}
    for (stop_id, uids, pname, plat_name, kb, ke, kbb, keb, agb, age, agbn, agen, cb, ce, nae) in plat_rows:
        p = {"k_board": kb, "k_exit": ke, "k_board_base": kbb, "k_exit_base": keb, "at_grade_board": agb,
             "at_grade_exit": age, "at_grade_board_now": agbn, "at_grade_exit_now": agen, "no_accessible_entrance": nae}
        assumptions = ["open-data model: GTFS pathways and facilities; lift status from MBTA alerts"]
        if any("#" in u for u in uids):
            assumptions.append("platform split into side and centre halves (model override)")
        row = {"id": stop_id, "uids": sorted(uids), "name": " ".join(x for x in (pname, plat_name) if x),
               **{k: p[k] for k in ("k_board", "k_exit", "k_board_base", "k_exit_base")},
               "cut_board": cb or [], "cut_exit": ce or [], "verdict": _verdict(p), "assumptions": assumptions}
        platforms.append(row)
        if nae or not streets:
            continue
        src, dst = (streets, uids) if direction == "board" else (uids, streets)
        d = redundancy.direction(g, flow_edges, lift_fac, src, dst)
        receipt_ms += d.ms
        for i, path in enumerate(d.routes):
            cids = []
            for raw in path:
                for c in raw_map.get(raw, []):
                    if not cids or cids[-1] != c:
                        cids.append(c)
            lifts = [lift_fac[e] for e in path if e in lift_fac]
            routes.append({"platform_id": stop_id, "dir": direction, "label": chr(ord("A") + i), "edge_ids": cids,
                           "lifts": lifts, "text": [f"lift {f}" for f in lifts] or ["no lift needed"]})
        if d.k == 1:
            for f in d.spof_facilities:
                last_lift.setdefault(f, []).append(stop_id)

    out_nodes = []
    for c, n in sorted(cnodes.items()):
        node = {"id": c, "kind": n["kind"], "label": n["label"], "rank": rank.get(c), "band": band.get(c)}
        if n["kind"] == "lift":
            fid = n.get("facility_id")
            node["facility_id"] = fid
            node["status"] = "sim_closed" if fid in closed and fid not in parent_closed else \
                "closed" if fid in closed else "open"
            if fid in last_lift:
                node["last_lift"] = sorted(last_lift[fid])
        if n["kind"] == "platform":
            pr = next((p for p in platforms if p["id"] == n.get("stop_id")), {})
            node.update(stop_id=n.get("stop_id"), k_board=pr.get("k_board"), k_exit=pr.get("k_exit"), wb=n.get("wb"))
        out_nodes.append(node)
    for fid, fname in g.ro_query(Q_STATION_UNMODELLED_LIFTS, {"sid": station_id}).result_set:
        out_nodes.append({"id": f"lift:{fid}", "kind": "lift", "label": fname, "facility_id": fid, "rank": None,
                          "band": None, "status": "unknown", "modelled": False})

    status = {n["id"]: n.get("status") for n in out_nodes if n["kind"] == "lift"}
    out_edges = []
    for e in sorted(cedges.values(), key=lambda x: x["id"]):
        x = {k: e[k] for k in ("id", "source", "target", "kind", "pathway_ids", "step_free")}
        if "facility_id" in e:
            x["facility_id"] = e["facility_id"]
        if e["kind"] == "lift":
            x["status"] = status.get(e["source"]) or status.get(e["target"]) or "open"
        out_edges.append(x)

    state_version = hashlib.sha1(f"{graph}|{','.join(closed)}".encode()).hexdigest()[:12]
    return {
        "schema_version": SCHEMA_VERSION,
        "station": {"id": sid, "name": name, "cx": cx, "has_pathways": bool(has_pw),
                    "has_accessible_entrance": bool(has_street),
                    "snapshot": {"id": meta[0][0], "seed_sha256": meta[0][1]} if meta else None,
                    "scope": scope, "scenario": scenario, "closed": closed, "state_version": state_version},
        "nodes": out_nodes, "edges": out_edges, "platforms": platforms, "routes": routes,
        "receipt": {"query_id": "Q_MAXFLOW", "algo": "algo.maxFlow", "certified": "exact or repaired, proof-checked",
                    "flow_ms": round(receipt_ms, 1), "ms": round((time.perf_counter() - started) * 1000, 1),
                    "graph": graph,
                    "queries": ["Q_STATION", "Q_STATION_NODES", "Q_STATION_EDGES", "Q_STATION_PLATFORMS",
                                "Q_COMPLEX_STREETS", "Q_COMPLEX_FLOW_EDGES", "Q_MAXFLOW"]},
    }
