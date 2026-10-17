"""Network-scale step-free analysis: which station-to-station journeys a lift closure breaks.

A journey a -> b (a != b) is step-free reachable when a path runs from the Street node of station a to the
Street node of station b over the graph's SF (walk, gate, lift) and RIDE (train or Silver Line) edges.
There is one Street node per station with an accessible entrance, so the origins and destinations are
those stations.

N-1 by dominator trees. Every lift unit is node-split (lift:L -> lift:L:out, and lift:L:out has exactly
one incoming edge), so closing unit L is the same as deleting the node lift:L:out. Fix an origin r: a
node x *dominates* t if every r -> t path passes through x. So the destinations that lose step-free
reachability from r when L closes are exactly the Street nodes in the dominator subtree of lift:L:out.
One dominator tree per origin (Cooper, Harvey and Kennedy's iterative algorithm) therefore gives the
journeys every lift breaks, all at once. The trees are built on the zone graph: the strongly connected
parts of the network without its lift edges, contracted. That is exact (no lift lies inside a zone, so a
lift dominates a node exactly when it dominates the node's zone) and much smaller. Facilities with several units are handled by a direct search
with all their units removed. `witness()` recomputes everything by plain search (one per lift per
origin) and the sweep reports how often the two agree.

Like routing, this runs in Python over the graph's own edges (read from FalkorDB): FalkorDB's path
procedures enumerate paths and can run for hours on this network (docs/falkordb-sppaths-note.md).
"""
import heapq
from collections import defaultdict
from dataclasses import dataclass

from .routing import Topology


@dataclass
class Impact:
    """What closing one facility does to the journeys between stations (relative to a starting state)."""
    facility_id: str
    broken: set            # {(origin station, destination station)} that lose step-free reachability
    cut_off: list          # stations that lose every journey to and from the rest of the network


class Net:
    def __init__(self, topo: Topology):
        uids = sorted(set(topo.nodes) | {e.b for es in topo.adj.values() for e in es} | set(topo.adj))
        self.uid = uids
        self.idx = {u: i for i, u in enumerate(uids)}
        n = len(uids)
        self.succ: list[list[int]] = [[] for _ in range(n)]
        self.wsucc: list[list[tuple[int, int]]] = [[] for _ in range(n)]
        self.pred: list[list[int]] = [[] for _ in range(n)]
        for a, es in topo.adj.items():
            for e in es:
                i, j = self.idx[a], self.idx[e.b]
                self.succ[i].append(j)
                self.wsucc[i].append((j, e.wt))
                self.pred[j].append(i)
        self.street: dict[str, int] = {}          # station id -> its Street node
        self.units: dict[str, list[int]] = defaultdict(list)    # facility id -> its lift:L:out nodes
        self.unit_facility: dict[int, str] = {}
        self.unit_station: dict[int, str] = {}
        for e in (e for es in topo.adj.values() for e in es):
            if e.kind == "lift" and e.facility_id:
                out = self.idx[e.b]
                self.units[e.facility_id].append(out)
                self.unit_facility[out] = e.facility_id
                self.unit_station[out] = (topo.nodes.get(e.a) or {}).get("station_id") or ""
        for u, meta in topo.nodes.items():
            if "Street" in (meta.get("labels") or []):
                self.street[meta["station_id"]] = self.idx[u]
        self.stations = sorted(self.street)
        self.street_station = {i: s for s, i in self.street.items()}
        self.names = {meta["station_id"]: meta["name"].removeprefix("Street (").removesuffix(")")
                      for meta in topo.nodes.values() if "Street" in (meta.get("labels") or [])}
        self._zones()

    def _zones(self):
        """Contract the strongly connected parts of the network without lift edges (Tarjan, iterative)."""
        n = len(self.uid)
        lift_out = set(self.unit_facility)
        succ = [[y for y in self.succ[x] if y not in lift_out] for x in range(n)]
        index, low, comp = [-1] * n, [0] * n, [-1] * n
        on, st, counter, nz = bytearray(n), [], 0, 0
        for v0 in range(n):
            if index[v0] != -1:
                continue
            work = [(v0, 0)]
            while work:
                v, i = work.pop()
                if i == 0:
                    index[v] = low[v] = counter
                    counter += 1
                    st.append(v)
                    on[v] = 1
                recurse = False
                while i < len(succ[v]):
                    w = succ[v][i]
                    i += 1
                    if index[w] == -1:
                        work.append((v, i))
                        work.append((w, 0))
                        recurse = True
                        break
                    if on[w]:
                        low[v] = min(low[v], index[w])
                if recurse:
                    continue
                if low[v] == index[v]:
                    while True:
                        w = st.pop()
                        on[w] = 0
                        comp[w] = nz
                        if w == v:
                            break
                    nz += 1
                if work:
                    u = work[-1][0]
                    low[u] = min(low[u], low[v])
        self.zone = comp
        zs = [set() for _ in range(nz)]
        for x in range(n):
            for y in self.succ[x]:
                if comp[x] != comp[y]:
                    zs[comp[x]].add(comp[y])
        self.zsucc = [sorted(z) for z in zs]
        zp = [[] for _ in range(nz)]
        for a, ys in enumerate(self.zsucc):
            for b in ys:
                zp[b].append(a)
        self.zpred = zp
        self.zone_facility = {comp[o]: f for o, f in self.unit_facility.items()}

    # --- basic search ---------------------------------------------------------------------------
    def banned_nodes(self, facilities) -> frozenset:
        return frozenset(o for f in facilities for o in self.units.get(f, ()))

    def banned_zones(self, facilities) -> frozenset:
        return frozenset(self.zone[o] for f in facilities for o in self.units.get(f, ()))

    def reach(self, root: int, banned: frozenset = frozenset()) -> bytearray:
        seen = bytearray(len(self.uid))
        seen[root] = 1
        stack = [root]
        succ = self.succ
        while stack:
            x = stack.pop()
            for y in succ[x]:
                if not seen[y] and y not in banned:
                    seen[y] = 1
                    stack.append(y)
        return seen

    def od(self, closed=(), zones=True) -> dict[str, set]:
        """origin station -> destination stations reachable step-free, with `closed` facilities out.
        zones=False searches the full network (the witness uses it: independent of the contraction)."""
        out = {}
        if zones:
            banned = self.banned_zones(closed)
            for a in self.stations:
                seen = self._zreach(self.zone[self.street[a]], banned)
                out[a] = {b for b in self.stations if b != a and self.zone[self.street[b]] in seen}
            return out
        banned = self.banned_nodes(closed)
        for a in self.stations:
            seen = self.reach(self.street[a], banned)
            out[a] = {b for b in self.stations if b != a and seen[self.street[b]]}
        return out

    def _zreach(self, root: int, banned: frozenset) -> set:
        seen = {root}
        stack = [root]
        zsucc = self.zsucc
        while stack:
            x = stack.pop()
            for y in zsucc[x]:
                if y not in seen and y not in banned:
                    seen.add(y)
                    stack.append(y)
        return seen

    def times(self, root: int, banned: frozenset = frozenset()) -> dict[int, int]:
        """Dijkstra seconds from `root` to every reachable node."""
        dist = {root: 0}
        heap = [(0, root)]
        wsucc = self.wsucc
        while heap:
            d, x = heapq.heappop(heap)
            if d > dist[x]:
                continue
            for y, w in wsucc[x]:
                if y in banned:
                    continue
                nd = d + w
                if nd < dist.get(y, 1 << 62):
                    dist[y] = nd
                    heapq.heappush(heap, (nd, y))
        return dist

    def tree_lifts(self, root: int) -> set:
        """Lift facilities used by one shortest-path tree from `root` to the other Street nodes. A closure
        that misses all of them leaves every travel time from `root` unchanged."""
        dist, prev = {root: 0}, {}
        heap = [(0, root)]
        while heap:
            d, x = heapq.heappop(heap)
            if d > dist[x]:
                continue
            for y, w in self.wsucc[x]:
                nd = d + w
                if nd < dist.get(y, 1 << 62):
                    dist[y], prev[y] = nd, x
                    heapq.heappush(heap, (nd, y))
        used, done = set(), {root}
        for t in self.street.values():
            x = t
            while x not in done and x in prev:
                done.add(x)
                if x in self.unit_facility:
                    used.add(self.unit_facility[x])
                x = prev[x]
        return used

    def travel_times(self, closed=()) -> dict[str, dict[str, int]]:
        banned = self.banned_nodes(closed)
        out = {}
        for a in self.stations:
            dist = self.times(self.street[a], banned)
            out[a] = {b: dist[self.street[b]] for b in self.stations if b != a and self.street[b] in dist}
        return out

    # --- dominators -----------------------------------------------------------------------------
    def idom(self, root: int, banned: frozenset = frozenset()) -> tuple[dict, dict]:
        """Immediate dominators of every zone reachable from zone `root` (Cooper-Harvey-Kennedy).
        Returns (idom, postorder number)."""
        succ, pred = self.zsucc, self.zpred
        po, order = {}, []
        visited = {root}
        stack = [(root, iter(succ[root]))]
        while stack:
            x, it = stack[-1]
            for y in it:
                if y not in visited and y not in banned:
                    visited.add(y)
                    stack.append((y, iter(succ[y])))
                    break
            else:
                stack.pop()
                po[x] = len(order)
                order.append(x)
        rpo = order[::-1]
        idom = {root: root}

        def meet(a, b):
            while a != b:
                while po[a] < po[b]:
                    a = idom[a]
                while po[b] < po[a]:
                    b = idom[b]
            return a

        changed = True
        while changed:
            changed = False
            for b in rpo[1:]:
                new = None
                for p in pred[b]:
                    if p in idom:
                        new = p if new is None else meet(p, new)
                if idom.get(b) != new:
                    idom[b] = new
                    changed = True
        return idom, po

    def n1(self, closed=()) -> dict[str, Impact]:
        """For every facility still open: the journeys its closure would break, given `closed` are out."""
        closed = set(closed)
        banned = self.banned_zones(closed)
        broken: dict[str, set] = defaultdict(set)
        single = {f for f, us in self.units.items() if len(us) == 1 and f not in closed}
        dominates_for: dict[str, set] = defaultdict(set)
        for a in self.stations:
            r = self.zone[self.street[a]]
            idom, _ = self.idom(r, banned)
            for b in self.stations:
                t = self.zone[self.street[b]]
                if b == a or t not in idom or t == r:
                    continue
                x = idom[t]
                while x != r:
                    f = self.zone_facility.get(x)
                    if f in single:
                        broken[f].add((a, b))
                        dominates_for[f].add(a)
                    x = idom[x]
        multi = [f for f, us in self.units.items() if len(us) > 1 and f not in closed]
        if multi:
            base = self.od(closed)
            for f in multi:
                after = self.od(closed | {f})
                broken[f] = {(a, b) for a in self.stations for b in base[a] - after[a]}
        self.dominates_for = dominates_for
        return {f: Impact(f, broken.get(f, set()), self._cut_off(broken.get(f, set()), closed))
                for f in sorted(self.units) if f not in closed}

    def _cut_off(self, broken: set, closed) -> list[str]:
        """Stations whose every still-reachable journey (both ways) is broken."""
        if not broken:
            return []
        out_b, in_b = defaultdict(int), defaultdict(int)
        for a, b in broken:
            out_b[a] += 1
            in_b[b] += 1
        base = self._od_cache(tuple(sorted(closed)))
        res = []
        for s in set(out_b) | set(in_b):
            reach_out = len(base[s])
            reach_in = sum(1 for a in self.stations if s in base[a])
            if out_b[s] == reach_out and in_b[s] == reach_in and reach_out + reach_in:
                res.append(s)
        return sorted(res)

    def _od_cache(self, closed: tuple):
        cache = self.__dict__.setdefault("_odc", {})
        if closed not in cache:
            cache[closed] = self.od(closed)
        return cache[closed]

    def witness(self, facility: str, closed=()) -> set:
        """The journeys closing `facility` breaks, by plain search over the full network (no zones, no
        dominators): the dominator method's independent check."""
        base = self.od(closed, zones=False)
        after = self.od(set(closed) | {facility}, zones=False)
        return {(a, b) for a in self.stations for b in base[a] - after[a]}


# --- per-process cache (the API and the agent's tools) ---------------------------------------------------
_nets: dict[str, Net] = {}
_results: "dict[tuple, object]" = {}
_lock = __import__("threading").Lock()
_RESULTS_MAX = 32


def get(base_graph: str) -> Net:
    from .routing import topology
    with _lock:
        if base_graph not in _nets:
            _nets[base_graph] = Net(topology(base_graph))
        return _nets[base_graph]


def cached(net: Net, kind: str, closed) -> object:
    """net.od(closed) or net.n1(closed), memoised per closed set (a closure state is asked about repeatedly)."""
    key = (id(net), kind, tuple(sorted(set(closed))))
    with _lock:
        if key in _results:
            return _results[key]
    value = net.od(key[2]) if kind == "od" else net.n1(key[2])
    with _lock:
        _results[key] = value
        while len(_results) > _RESULTS_MAX:
            _results.pop(next(iter(_results)))
    return value
