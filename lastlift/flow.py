"""Max-flow certification, repair and min-cut extraction (pure Python, no database calls).

FalkorDB 4.22's algo.maxFlow can return a non-maximal, non-conserving flow on some node-split
networks (reproduced on our instance). LastLift therefore never trusts a max-flow value on its own:

  1. certify()   - the returned flow must be feasible (0 <= f <= cap, conservation at inner nodes)
                   and maximal (no source-to-sink path left in the residual graph). By max-flow /
                   min-cut duality a feasible flow with no augmenting path is optimal.
  2. repair()    - if certification fails, solve exactly (Dinic) on the same edge list.
  3. min_cut()   - edges leaving the residual-reachable side; their capacity sum equals the flow.
  4. decompose() - split an integral flow into unit paths (one per lift-disjoint route).

Edges are (eid, u, v, cap) tuples. Sources and sinks are node ids.
"""
from collections import defaultdict, deque
from dataclasses import dataclass, field

TOL = 1e-6


@dataclass
class Certificate:
    feasible: bool
    maximal: bool
    value: float
    reachable: set = field(default_factory=set, repr=False)

    @property
    def ok(self) -> bool:
        return self.feasible and self.maximal


def _residual_reach(edges, flow, sources):
    adj = defaultdict(list)
    for eid, u, v, cap in edges:
        f = flow.get(eid, 0.0)
        if f < cap - TOL:
            adj[u].append(v)
        if f > TOL:
            adj[v].append(u)
    seen, queue = set(sources), deque(sources)
    while queue:
        x = queue.popleft()
        for y in adj[x]:
            if y not in seen:
                seen.add(y)
                queue.append(y)
    return seen


def certify(edges, flow, sources, sinks) -> Certificate:
    balance = defaultdict(float)
    feasible = True
    for eid, u, v, cap in edges:
        f = flow.get(eid, 0.0)
        if f < -TOL or f > cap + TOL:
            feasible = False
        balance[u] -= f
        balance[v] += f
    terminals = set(sources) | set(sinks)
    if any(abs(b) > TOL for n, b in balance.items() if n not in terminals):
        feasible = False
    known = {eid for eid, *_ in edges}
    if any(eid not in known for eid in flow):
        feasible = False  # flow on an edge outside the network under test
    value = sum(balance[t] for t in sinks)
    reach = _residual_reach(edges, flow, list(sources))
    return Certificate(feasible, not (reach & set(sinks)), value, reach)


class _Dinic:
    def __init__(self):
        self.graph = defaultdict(list)   # node -> list of [to, cap, rev_index, eid]

    def add(self, u, v, cap, eid=None):
        self.graph[u].append([v, cap, len(self.graph[v]), eid])
        self.graph[v].append([u, 0, len(self.graph[u]) - 1, None])

    def maxflow(self, s, t):
        total = 0
        while True:
            level = {s: 0}
            q = deque([s])
            while q:
                x = q.popleft()
                for to, cap, _, _ in self.graph[x]:
                    if cap > 0 and to not in level:
                        level[to] = level[x] + 1
                        q.append(to)
            if t not in level:
                return total
            it = defaultdict(int)

            def dfs(x, pushed):
                if x == t:
                    return pushed
                edges = self.graph[x]
                while it[x] < len(edges):
                    e = edges[it[x]]
                    to, cap, rev, _ = e
                    if cap > 0 and level.get(to) == level[x] + 1:
                        got = dfs(to, min(pushed, cap))
                        if got:
                            e[1] -= got
                            self.graph[to][rev][1] += got
                            return got
                    it[x] += 1
                return 0

            while True:
                pushed = dfs(s, float("inf"))
                if not pushed:
                    break
                total += pushed


def exact_maxflow(edges, sources, sinks):
    """Exact max-flow (Dinic) with a super source/sink. Returns (value, {eid: flow})."""
    d = _Dinic()
    super_s, super_t = ("__S__",), ("__T__",)
    caps = {}
    for eid, u, v, cap in edges:
        d.add(u, v, cap, eid)
        caps[eid] = cap
    for s in sources:
        d.add(super_s, s, float("inf"))
    for t in sinks:
        d.add(t, super_t, float("inf"))
    import sys
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 20000))
    try:
        value = d.maxflow(super_s, super_t)
    finally:
        sys.setrecursionlimit(old)
    flow = {}
    for u, adj in d.graph.items():
        for to, cap, rev, eid in adj:
            if eid is not None:
                f = caps[eid] - cap
                if f:
                    flow[eid] = f
    return value, flow


def repair(edges, flow, sources, sinks):
    """Certify a returned flow; if it fails, replace it with an exact solution.

    Returns (value, flow, outcome) with outcome 'exact' (accepted as returned) or 'repaired'."""
    cert = certify(edges, flow, sources, sinks)
    if cert.ok:
        return cert.value, flow, "exact"
    value, fixed = exact_maxflow(edges, sources, sinks)
    if not certify(edges, fixed, sources, sinks).ok:  # never expected; refuse to state a number
        raise RuntimeError("exact solver produced an uncertifiable flow")
    return value, fixed, "repaired"


def min_cut(edges, flow, sources):
    """Edges from the residual-reachable side to the rest (the minimum cut)."""
    reach = _residual_reach(edges, flow, list(sources))
    return [e for e in edges if e[1] in reach and e[2] not in reach]


def decompose(edges, flow, sources, sinks, limit=64):
    """Split an integral flow into source-to-sink unit paths (lists of edge ids).

    Breadth-first search over edges that still carry flow; by the flow-decomposition theorem a
    source-to-sink path exists while flow remains, even when the flow contains cycles."""
    remaining = {eid: int(round(f)) for eid, f in flow.items() if f > TOL}
    out_edges = defaultdict(list)
    for eid, u, v, cap in edges:
        out_edges[u].append((eid, v))
    sinks = set(sinks)
    paths = []
    while len(paths) < limit:
        parent = {s: None for s in sources}
        queue = deque(sources)
        end = None
        while queue and end is None:
            x = queue.popleft()
            for eid, v in out_edges[x]:
                if remaining.get(eid, 0) > 0 and v not in parent:
                    parent[v] = (x, eid)
                    if v in sinks:
                        end = v
                        break
                    queue.append(v)
        if end is None:
            break
        path, node = [], end
        while parent[node] is not None:
            node, eid = parent[node]
            path.append(eid)
        path.reverse()
        for eid in path:
            remaining[eid] -= 1
        paths.append(path)
    return paths
