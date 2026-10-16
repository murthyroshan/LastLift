"""Certified lift redundancy for one platform, computed live in FalkorDB.

Every value is: FalkorDB algo.maxFlow -> certified (or exactly repaired) -> min cut -> k-path proof
checked by the independent checker. Used by the baseline sweep, the live closure sync, what-if
copies and the agent's platform_redundancy tool, so all of them share one code path.
"""
import time
from dataclasses import dataclass, field

from .checker import check
from .flow import decompose, exact_maxflow, min_cut, repair
from .queries import Q_COMPLEX_FLOW_EDGES, Q_MAXFLOW

BIG = 1_000_000


@dataclass
class Direction:
    k: int | None              # None = at grade (no lift needed) or not assessable
    at_grade: bool
    cut_facilities: list[str] = field(default_factory=list)
    spof_facilities: list[str] = field(default_factory=list)  # k == 1: every lift whose loss alone cuts access
    routes: list[list[str]] = field(default_factory=list)   # edge-id paths, one per lift-disjoint route
    outcome: str = "exact"     # exact | repaired
    proof: str = "n/a"         # accepted | rejected:<reason> | n/a
    ms: float = 0.0


def complex_edges(g, cx):
    """All step-free edges in a complex: [(eid, u, v, cap)], lift edge -> facility map, kinds."""
    rows = g.ro_query(Q_COMPLEX_FLOW_EDGES, {"cx": cx}).result_set
    edges = [(r[0], r[1], r[2], r[3]) for r in rows]
    lift_facility = {r[0]: r[5] for r in rows if r[4] == "lift"}
    return edges, lift_facility


def direction(g, edges, lift_facility, sources, sinks) -> Direction:
    started = time.perf_counter()
    rs = g.ro_query(Q_MAXFLOW, {"src": sources, "dst": sinks}).result_set
    eids, flows, _ = rs[0] if rs else ([], [], 0.0)
    value, flow, outcome = repair(edges, dict(zip(eids, flows)), sources, sinks)
    k = int(round(value))
    d = Direction(k=None if k >= BIG else k, at_grade=k >= BIG, outcome=outcome)
    if 0 < k < BIG:
        cut = [e[0] for e in min_cut(edges, flow, sources)]
        paths = decompose(edges, flow, sources, sinks)
        verdict = check(edges, lift_facility.keys(), sources, sinks, k, paths, cut)
        d.cut_facilities = sorted({lift_facility[e] for e in cut})
        d.routes = paths
        d.proof = "accepted" if verdict.accepted else f"rejected:{verdict.reason}"
        if k == 1:
            # Lifts in series on the only route are all single points of failure, not just the
            # one the min cut happens to pick. Test each lift on the route by removing it.
            on_route = {e for e in paths[0] if e in lift_facility} if paths else set()
            d.spof_facilities = sorted({lift_facility[e] for e in on_route
                                        if exact_maxflow([x for x in edges if x[0] != e], sources, sinks)[0] == 0})
    d.ms = round((time.perf_counter() - started) * 1000, 1)
    return d


def platform(g, cx, platform_uids, street_uids, edges=None, lift_facility=None):
    """Board and exit redundancy for one platform (all of its uids, e.g. both halves of a split stop)."""
    if not street_uids:
        return None
    if edges is None:
        edges, lift_facility = complex_edges(g, cx)
    return {"board": direction(g, edges, lift_facility, street_uids, platform_uids),
            "exit": direction(g, edges, lift_facility, platform_uids, street_uids)}
