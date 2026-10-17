"""What one lift alert does to step-free access, computed in FalkorDB.

For a set of closed facilities (one MBTA alert), on a what-if copy of the base graph:
  * every platform-direction in the affected complexes is recomputed (certified maxFlow);
  * a direction is LOST when it had step-free access before and has none now;
  * an accessible entrance is CUT OFF when it reached a platform before and reaches none now;
  * for each lost direction, a network reroute is searched (ride on and come back, etc.).

Verdicts (same vocabulary as validation/LABELLING_GUIDE.md):
  LOSS          some platform-direction loses step-free access inside the station
  ENTRANCE_ONLY no platform loses access, but an accessible entrance is cut off
  NO_LOSS       everything that was reachable still is
  CANNOT_ASSESS none of the alert's facilities is in the step-free model
"""
from collections import defaultdict

from . import db, redundancy, routing, state
from .queries import Q_COMPLEX_PLATFORMS, Q_LIFT_COMPLEXES, Q_MODELLED_LIFTS


def _reach(adj, sources, targets, banned, inside=False):
    """Step-free reachability avoiding `banned` edges. inside=True never passes through the station's
    virtual street node, so an entrance only counts as connected by a route inside the station."""
    seen, todo, targets = set(sources), list(sources), set(targets)
    while todo:
        u = todo.pop()
        if u in targets:
            return True
        for v, eid in adj.get(u, ()):
            if inside and v.startswith("street:"):
                continue
            if eid not in banned and v not in seen:
                seen.add(v)
                todo.append(v)
    return False


def assess(facility_ids, base_scope: str = "base") -> dict:
    base = state.graph_name(base_scope)
    g = db.client().select_graph(base)
    fids = sorted({str(f) for f in facility_ids})
    modelled = sorted(g.ro_query(Q_MODELLED_LIFTS, {"fids": fids}).result_set[0][0])
    out = {"facility_ids": fids, "modelled": modelled, "platforms": [], "lost": {"board": [], "exit": []},
           "entrances_cut": [], "alt_lifts": [], "reroute": {}, "classes": {}}
    if not modelled:
        out.update(verdict="CANNOT_ASSESS", reason="none of these facilities is in the step-free model "
                                                   "(no pathway data for the station, or not an elevator)")
        return out

    wi = state.what_if(base_scope, modelled)
    cg = db.client().select_graph(wi["copy"])
    complexes = g.ro_query(Q_LIFT_COMPLEXES, {"fids": modelled}).result_set[0][0]
    base_topo = routing.topology(base)
    alt, lost_any = set(), defaultdict(list)
    for cx in sorted(complexes):
        edges, lift_fac = redundancy.complex_edges(g, cx)
        c_edges, c_fac = redundancy.complex_edges(cg, cx)
        closed_eids = {e for e, f in lift_fac.items() if f in modelled}
        adj = defaultdict(list)
        for eid, u, v, _cap in edges:
            adj[u].append((v, eid))
        streets = sorted({u for _, u, _, _ in edges if u.startswith("street:")})
        entrances = sorted({v for _, u, v, _ in edges if u.startswith("street:")})
        plats = g.ro_query(Q_COMPLEX_PLATFORMS, {"cx": cx}).result_set
        all_plat_uids = [u for row in plats for u in row[1]]
        for ent in entrances:
            before = _reach(adj, [ent], all_plat_uids, set(), True) or \
                any(_reach(adj, [p], [ent], set(), True) for p in all_plat_uids)
            after = _reach(adj, [ent], all_plat_uids, closed_eids, True) or \
                any(_reach(adj, [p], [ent], closed_eids, True) for p in all_plat_uids)
            if before and not after:
                out["entrances_cut"].append(ent)
        if not streets:
            continue
        for stop_id, uids, pname, wb, plat_name in plats:
            row = {"stop_id": stop_id, "name": " ".join(x for x in (pname, plat_name) if x), "cx": cx}
            for d in ("board", "exit"):
                src, dst = (streets, uids) if d == "board" else (uids, streets)
                had = _reach(adj, src, dst, set())
                now = _reach(adj, src, dst, closed_eids)
                b = redundancy.direction(g, edges, lift_fac, src, dst)
                c = redundancy.direction(cg, c_edges, c_fac, src, dst)
                used_closed = any(e in closed_eids for path in b.routes for e in path) or \
                    bool(set(b.cut_facilities) & set(modelled))
                row[d] = {"k_before": "at grade" if b.at_grade else b.k, "k_after": "at grade" if c.at_grade else c.k,
                          "lost": had and not now, "affected": used_closed, "certified": c.outcome}
                if had and not now:
                    lost_any[d].append(stop_id)
                    r = base_topo.shortest(src, dst, modelled)
                    row[d]["reroute"] = None if r is None else {
                        "minutes": round(r[0] / 60, 1), "lifts": [e.facility_id for e in r[1] if e.kind == "lift"],
                        "steps": [s["text"] for s in routing.describe(base_topo, r[1])],
                        "type": "RIDE_AND_RETURN" if any(e.type == "RIDE" for e in r[1]) else "IN_STATION"}
                elif used_closed:
                    alt |= {c_fac[e] for path in c.routes for e in path if e in c_fac}
            if any(row[d]["lost"] or row[d]["affected"] for d in ("board", "exit")):
                out["platforms"].append(row)

    out["lost"] = {d: sorted(set(v)) for d, v in lost_any.items()}
    out["alt_lifts"] = sorted(alt - set(modelled))
    for d in ("board", "exit"):
        rr = [p[d].get("reroute") for p in out["platforms"] if p[d]["lost"]]
        if rr:
            types = {r["type"] for r in rr if r} | ({"NO_ROUTE"} if None in rr else set())
            out["classes"][d] = "NO_ROUTE" if types == {"NO_ROUTE"} else sorted(types - {"NO_ROUTE"})[0]
        elif any(p[d]["affected"] for p in out["platforms"]):
            out["classes"][d] = "IN_STATION"
        else:
            out["classes"][d] = "UNAFFECTED"
    if out["lost"].get("board") or out["lost"].get("exit"):
        out["verdict"] = "LOSS"
    elif out["entrances_cut"]:
        out["verdict"] = "ENTRANCE_ONLY"
    else:
        out["verdict"] = "NO_LOSS"
    out["copy"] = wi["copy"]
    return out
