"""Everything about *which* lifts a platform-direction depends on (pure Python, on one complex's SF edges).

  all_min_cuts()   every minimum set of lift units whose loss cuts the platform-direction off
                   (Picard-Queyranne: the minimum cuts are exactly the closed sets of the residual graph
                   of a maximum flow that contain the sources and not the sinks);
  brute_min_cuts() the same by trying every k-subset of lift units (the test oracle, no flow involved);
  Failures         every set of lift *facilities* whose joint closure cuts a platform-direction off,
                   found by exhaustive search over the facilities that lie on some route. It gives the
                   minimal failure sets (size 1 = single points of failure, size 2 = critical pairs, N-2),
                   the exact reliability polynomial, and the per-lift N-1 table.

Reliability. If every lift is out of service independently with probability q, the probability that a
platform-direction has no step-free route is R(q) = sum_j N_j q^j (1-q)^(n-j), where N_j counts the
failing facility sets of size j among the n relevant facilities. For small q, R(q) ~ c_k q^k, where k is
the certified max-flow and c_k the number of minimum cuts. The "nines" are -log10 R(q).
"""
import math
from collections import defaultdict, deque
from itertools import combinations

from .flow import TOL

MAX_ENUM = 16          # exhaustive failure-set search up to 2^16 facility subsets per platform-direction


def _reach(adj, start):
    seen = set(start)
    q = deque(start)
    while q:
        x = q.popleft()
        for y in adj.get(x, ()):
            if y not in seen:
                seen.add(y)
                q.append(y)
    return seen


def _adj(edges, skip=frozenset(), reverse=False):
    adj = defaultdict(list)
    for eid, u, v, _ in edges:
        if eid not in skip:
            if reverse:
                adj[v].append(u)
            else:
                adj[u].append(v)
    return adj


def connected(edges, sources, sinks, skip=frozenset()) -> bool:
    return bool(_reach(_adj(edges, skip), sources) & set(sinks))


def relevant_edges(edges, sources, sinks):
    """Edges on some source-to-sink route (both ends reachable from a source and able to reach a sink)."""
    fwd = _reach(_adj(edges), sources)
    bwd = _reach(_adj(edges, reverse=True), sinks)
    return [e for e in edges if e[1] in fwd and e[2] in bwd]


# --- all minimum cuts (Picard-Queyranne) ---------------------------------------------------------
def all_min_cuts(edges, flow, sources, sinks, lift_facility, limit=50_000):
    """Every minimum cut of a maximum flow, as sorted tuples of lift edge ids. Returns (cuts, complete).
    `complete` is False only if more than `limit` closed sets had to be visited (never seen here)."""
    edges = relevant_edges(edges, sources, sinks)
    radj, rrev = defaultdict(list), defaultdict(list)
    for eid, u, v, cap in edges:
        f = flow.get(eid, 0.0)
        if f < cap - TOL:
            radj[u].append(v)
            rrev[v].append(u)
        if f > TOL:
            radj[v].append(u)
            rrev[u].append(v)
    s_side = _reach(radj, sources)                  # in every minimum cut's source side
    t_side = _reach(rrev, sinks)                    # in no minimum cut's source side
    nodes = {x for e in edges for x in e[1:3]}
    middle = sorted(nodes - s_side - t_side, key=str)
    comp = _scc(middle, radj)
    comps = sorted(set(comp.values()))
    csucc = defaultdict(set)
    for x in middle:
        for y in radj.get(x, ()):
            if y in comp and comp[y] != comp[x]:
                csucc[comp[x]].add(comp[y])
    order = _topo(comps, csucc)[::-1]               # successors before predecessors
    lift_edges = [e for e in edges if e[0] in lift_facility]
    cuts, visited = set(), 0
    chosen = set()

    def cut_of():
        side = s_side | {x for x in middle if comp[x] in chosen}
        return tuple(sorted(e[0] for e in lift_edges if e[1] in side and e[2] not in side))

    def walk(i):
        nonlocal visited
        visited += 1
        if visited > limit:
            return False
        if i == len(order):
            cuts.add(cut_of())
            return True
        c = order[i]
        if not walk(i + 1):
            return False
        if csucc[c] <= chosen:
            chosen.add(c)
            ok = walk(i + 1)
            chosen.discard(c)
            return ok
        return True

    complete = walk(0)
    return sorted(cuts), complete


def _scc(nodes, adj):
    """Tarjan on the subgraph induced by `nodes`; returns node -> component number."""
    inside = set(nodes)
    index, low, comp, on, st = {}, {}, {}, set(), []
    counter = [0]
    n_comp = [0]
    for v0 in nodes:
        if v0 in index:
            continue
        work = [(v0, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter[0]
                counter[0] += 1
                st.append(v)
                on.add(v)
            succ = [w for w in adj.get(v, ()) if w in inside]
            recurse = False
            while i < len(succ):
                w = succ[i]
                i += 1
                if w not in index:
                    work.append((v, i))
                    work.append((w, 0))
                    recurse = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if recurse:
                continue
            if low[v] == index[v]:
                while True:
                    w = st.pop()
                    on.discard(w)
                    comp[w] = n_comp[0]
                    if w == v:
                        break
                n_comp[0] += 1
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
    return comp


def _topo(comps, succ):
    indeg = {c: 0 for c in comps}
    for c in comps:
        for d in succ[c]:
            indeg[d] += 1
    q = deque(sorted(c for c in comps if indeg[c] == 0))
    out = []
    while q:
        c = q.popleft()
        out.append(c)
        for d in sorted(succ[c]):
            indeg[d] -= 1
            if indeg[d] == 0:
                q.append(d)
    return out


def brute_min_cuts(edges, lift_facility, sources, sinks, k):
    """Oracle: every k-subset of lift edges on a route whose removal disconnects (no flow code at all)."""
    lifts = sorted(e[0] for e in relevant_edges(edges, sources, sinks) if e[0] in lift_facility)
    return sorted(tuple(sorted(c)) for c in combinations(lifts, k)
                  if not connected(edges, sources, sinks, frozenset(c)))


def facility_sets(cuts, lift_facility):
    return sorted({tuple(sorted({lift_facility[e] for e in c})) for c in cuts})


# --- failure sets, N-2 pairs, reliability, N-1 -----------------------------------------------------
class Failures:
    """Exhaustive facility-failure analysis for one platform-direction."""

    def __init__(self, edges, lift_facility, sources, sinks):
        rel = relevant_edges(edges, sources, sinks)
        self.facilities = sorted({lift_facility[e[0]] for e in rel if e[0] in lift_facility})
        self.n = len(self.facilities)
        self.complete = self.n <= MAX_ENUM
        by_fac = defaultdict(set)
        for e in rel:
            if e[0] in lift_facility:
                by_fac[lift_facility[e[0]]].add(e[0])
        self.counts = [0] * (self.n + 1)            # N_j: failing facility sets of size j
        self.minimal: list[tuple] = []
        if not self.complete:
            return
        bit = {f: 1 << i for i, f in enumerate(self.facilities)}
        failing_masks = []
        # increasing size, so every failing set found by search has no failing subset yet => minimal
        for size in range(self.n + 1):
            for combo in combinations(self.facilities, size):
                mask = sum(bit[f] for f in combo)
                if any(m & mask == m for m in failing_masks):
                    continue
                skip = frozenset(e for f in combo for e in by_fac[f])
                if not connected(rel, sources, sinks, skip):
                    failing_masks.append(mask)
                    self.minimal.append(combo)
        for mask in range(1 << self.n):
            if any(m & mask == m for m in failing_masks):
                self.counts[bin(mask).count("1")] += 1

    def reliability(self, q: float) -> float:
        """P(no step-free route) when each relevant lift is out independently with probability q."""
        return sum(c * q ** j * (1 - q) ** (self.n - j) for j, c in enumerate(self.counts))

    def nines(self, q: float) -> float | None:
        r = self.reliability(q)
        return None if r <= 0 else round(-math.log10(r), 2)

    def singles(self) -> list[str]:
        return [c[0] for c in self.minimal if len(c) == 1]

    def pairs(self) -> list[tuple]:
        return [c for c in self.minimal if len(c) == 2]


def monte_carlo(failures: Failures, edges, lift_facility, sources, sinks, q, samples, rng):
    """Sampled P(no route), with a Wilson 95% interval: the reliability polynomial's independent check."""
    rel = relevant_edges(edges, sources, sinks)
    by_fac = defaultdict(set)
    for e in rel:
        if e[0] in lift_facility:
            by_fac[lift_facility[e[0]]].add(e[0])
    fails = 0
    for _ in range(samples):
        down = [f for f in failures.facilities if rng.random() < q]
        skip = frozenset(e for f in down for e in by_fac[f])
        fails += not connected(rel, sources, sinks, skip)
    return fails / samples, wilson(fails, samples)


def wilson(x, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = x / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))
