"""Step-free routing across the network.

Why not algo.SPpaths: on FalkorDB 4.22 it enumerates paths. An unbounded South Station -> Alewife call
over SF + RIDE did not finish in 8 hours, a Revere Beach reroute with pathCount 2 never returned, and
even an SF-only call inside South Station bounded by maxCost and maxLen ran for minutes. The server's
query timeout (TIMEOUT_MAX) does not stop it. So no request path calls SPpaths:

  1. route   - Dijkstra over the graph's own SF + RIDE edges (topology read from FalkorDB once per
               process; closures read live from the scope graph on every call);
  2. certify - every edge of the route is re-read from the scope graph (indexed MATCH): it must exist,
               be open (SF, not SF_CLOSED) and carry the weight used. Optimality is Dijkstra's; the
               tests check it against NetworkX;
  3. backup  - the second route avoids every lift the first one uses ("if those lifts fail too").
"""
import heapq
import threading
from dataclasses import dataclass, field

from . import db
from .queries import Q_CLOSED_FACILITIES, Q_ROUTE_CHECK_RIDE, Q_ROUTE_CHECK_SF, Q_ROUTE_EDGES, Q_ROUTE_NODES

@dataclass
class Edge:
    a: str
    b: str
    eid: str
    type: str                  # SF | RIDE
    kind: str | None           # SF kind: walk | gate | street | lift_access | lift
    wt: int
    facility_id: str | None = None
    routes: list[str] = field(default_factory=list)


class Topology:
    def __init__(self, nodes: dict, edges: list[Edge]):
        self.nodes = nodes     # uid -> {name, labels, station_id, platform_name, short_name}
        self.adj: dict[str, list[Edge]] = {}
        for e in edges:
            self.adj.setdefault(e.a, []).append(e)

    @classmethod
    def from_rows(cls, node_rows, edge_rows):
        nodes = {r["uid"]: r for r in node_rows}
        edges = [Edge(r["a"], r["b"], r["eid"], r["type"], r.get("kind"), int(r["wt"]), r.get("facility_id"),
                      list(r.get("routes") or [])) for r in edge_rows if r["type"] in ("SF", "RIDE")]
        return cls(nodes, edges)

    @classmethod
    def from_graph(cls, g):
        nodes = {uid: {"uid": uid, "labels": labels, "name": name, "station_id": sid, "platform_name": pname,
                       "short_name": short} for uid, labels, name, sid, pname, short in g.ro_query(Q_ROUTE_NODES).result_set}
        edges = [Edge(a, b, eid, t, kind, int(wt), fid, list(rts or []))
                 for a, b, eid, t, kind, wt, fid, rts in g.ro_query(Q_ROUTE_EDGES).result_set]
        return cls(nodes, edges)

    def shortest(self, sources, targets, banned_facilities=()):
        """Multi-source Dijkstra. Returns (cost, [Edge, ...]) or None. Lift edges whose facility is
        banned (closed, or avoided for a backup route) are skipped."""
        banned, targets = set(banned_facilities), set(targets)
        dist, prev, heap, seq = {}, {}, [], 0
        for s in sources:
            if s in self.adj or s in targets:
                dist[s] = 0
                heapq.heappush(heap, (0, seq, s))
                seq += 1
        while heap:
            d, _, u = heapq.heappop(heap)
            if d > dist.get(u, float("inf")):
                continue
            if u in targets:
                path = []
                while u in prev:
                    path.append(prev[u])
                    u = prev[u].a
                return d, path[::-1]
            for e in self.adj.get(u, ()):
                if e.kind == "lift" and e.facility_id in banned:
                    continue
                nd = d + e.wt
                if nd < dist.get(e.b, float("inf")):
                    dist[e.b], prev[e.b] = nd, e
                    seq += 1
                    heapq.heappush(heap, (nd, seq, e.b))
        return None


_topo: dict[str, Topology] = {}
_topo_lock = threading.Lock()


def topology(base_graph: str) -> Topology:
    """The base topology (no closures), loaded from FalkorDB once per process."""
    with _topo_lock:
        if base_graph not in _topo:
            _topo[base_graph] = Topology.from_graph(db.client().select_graph(base_graph))
        return _topo[base_graph]


def closed_facilities(g) -> list[str]:
    rs = g.ro_query(Q_CLOSED_FACILITIES).result_set
    return sorted(rs[0][0]) if rs else []


# --- describing a route -------------------------------------------------------------------------
def segments(path: list[Edge]):
    """Split a path into ('walk', [SF edges]) and ('ride', [RIDE edges]) runs. A ride run is broken
    at a turnaround (the train would revisit a station already passed in this run) and where the
    routes of consecutive ride edges do not overlap (a change of train on the same platform)."""
    out = []
    for e in path:
        kind = "ride" if e.type == "RIDE" else "walk"
        if out and out[-1][0] == kind == "walk":
            out[-1][1].append(e)
            continue
        if out and out[-1][0] == kind == "ride":
            run = out[-1][1]
            seen = {run[0].a} | {x.b for x in run}
            same_line = set(e.routes) & set.intersection(*(set(x.routes) for x in run))
            if e.b not in seen and same_line:
                run.append(e)
                continue
        out.append((kind, [e]))
    return out


def describe(topo: Topology, path: list[Edge]) -> list[dict]:
    """Human steps: enter, lifts, rides (with line and turnarounds), changes, exit."""
    name = lambda uid: topo.nodes.get(uid, {}).get("name") or uid
    station = lambda uid: topo.nodes.get(uid, {}).get("station_id") or uid
    platform = lambda uid: " ".join(x for x in (name(uid), topo.nodes.get(uid, {}).get("platform_name")) if x)
    steps, segs, ridden = [], segments(path), set()      # ridden: stations already passed by train
    change_at = None                                     # index of the 'change' step since the last ride
    for i, (kind, run) in enumerate(segs):
        if kind == "ride":
            lines = sorted(set.intersection(*(set(x.routes) for x in run))) or sorted({r for x in run for r in x.routes})
            back = station(run[0].b) in ridden            # heading back over track already ridden
            if i and segs[i - 1][0] == "ride":            # train-to-train with no walk between
                steps.append({"kind": "turnaround" if back else "change", "at": run[0].a,
                              "text": (f"turn around at {name(run[0].a)}" if back else
                                       f"change to {'/'.join(lines)} at {name(run[0].a)}")})
            elif back and change_at is not None:
                c = steps[change_at]
                c.update(kind="turnaround", text=f"turn around at {c['name']} (step-free change of platform)")
            change_at = None
            steps.append({"kind": "ride", "text": f"ride {'/'.join(lines)} {'back ' if back else ''}to {name(run[-1].b)}",
                          "lines": lines, "from": run[0].a, "to": run[-1].b, "stops": len(run),
                          "seconds": sum(x.wt for x in run), "back": back})
            ridden |= {station(run[0].a)} | {station(x.b) for x in run}
            continue
        lifts = [x for x in run if x.kind == "lift"]
        first, last = i == 0, i == len(segs) - 1
        if first and run[0].a.startswith("street:"):
            steps.append({"kind": "enter", "text": f"enter at {name(run[0].b)}", "at": run[0].b})
        elif not first and not last:
            change_at = len(steps)
            steps.append({"kind": "change", "text": f"change at {name(run[0].a)} (step-free)", "at": run[0].a,
                          "name": name(run[0].a)})
        for x in lifts:
            short = topo.nodes.get(x.a, {}).get("short_name")
            steps.append({"kind": "lift", "text": f"lift {x.facility_id}" + (f" ({short})" if short else ""),
                          "facility_id": x.facility_id, "edge": x.eid})
        if last and run[-1].b.startswith("street:"):
            steps.append({"kind": "exit", "text": f"exit to the street at {name(run[-1].a)}", "at": run[-1].a})
    if path and not path[0].a.startswith("street:"):
        steps.insert(0, {"kind": "start", "text": f"start on the {platform(path[0].a)} platform", "at": path[0].a})
    if path and not path[-1].b.startswith("street:"):
        steps.append({"kind": "arrive", "text": f"arrive on the {platform(path[-1].b)} platform", "at": path[-1].b})
    return steps


# --- certification ------------------------------------------------------------------------------
def certify_route(g, path: list[Edge]) -> dict:
    """Re-read every edge of the route from the scope graph: present, open and with the weight used."""
    want = {"SF": {}, "RIDE": {}}
    for e in path:
        want[e.type][(e.a, e.b)] = e.wt
    found = {}
    for t, q in (("SF", Q_ROUTE_CHECK_SF), ("RIDE", Q_ROUTE_CHECK_RIDE)):
        if want[t]:
            for a, b, wt in g.ro_query(q, {"pairs": [list(k) for k in want[t]]}).result_set:
                found[(t, a, b)] = int(wt)
    missing = [f"{t}:{a}>{b}" for t in want for (a, b) in want[t] if (t, a, b) not in found]
    wrong = [f"{t}:{a}>{b}" for t in want for (a, b), w in want[t].items() if found.get((t, a, b), w) != w]
    status = "certified" if not missing and not wrong else "rejected"
    return {"status": status, "edges_checked": len(path), "missing_or_closed": missing, "weight_mismatch": wrong,
            "query_ids": ["Q_ROUTE_CHECK_SF", "Q_ROUTE_CHECK_RIDE"]}


def route(scope_graph: str, base_graph: str, sources, targets, alternatives: int = 2, certify: bool = True):
    """Best step-free route and up to `alternatives - 1` lift-disjoint backups."""
    topo = topology(base_graph)
    g = db.client().select_graph(scope_graph)
    closed = closed_facilities(g)
    routes, avoid = [], set()
    for i in range(max(1, alternatives)):
        found = topo.shortest(sources, targets, set(closed) | avoid)
        if found is None:
            break
        cost, path = found
        lifts = [e.facility_id for e in path if e.kind == "lift"]
        r = {"label": chr(ord("A") + i), "seconds": cost, "minutes": round(cost / 60, 1), "lifts": lifts,
             "steps": describe(topo, path), "edge_ids": [e.eid for e in path],
             "nodes": [path[0].a] + [e.b for e in path] if path else list(sources)[:1],
             "avoids": sorted(avoid)}
        if certify:
            r["certification"] = certify_route(g, path)
            r["certified"] = r["certification"]["status"] == "certified"
        routes.append(r)
        if not lifts:
            break                       # no lift on the route: nothing to back up
        avoid |= set(lifts)
    return {"closed": closed, "routes": routes}
