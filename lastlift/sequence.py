"""Repair sequencing: the order to reopen closed lifts that gives riders back the most, soonest.

After each repair the network is in a new state; its value is (journeys between stations reachable step-free,
platform-directions with step-free access), compared journeys first. A repair order's score is the sum of the
values after each step (the area under the "restored" curve), so an order that restores a lot early scores
higher. The exact best order comes from dynamic programming over the subsets already repaired (2^C states,
the same optimum as trying all C! orders); it runs when C <= EXACT_MAX. Greedy (always repair the lift that
helps most next) is computed as well, and the gap between the two is reported, never hidden.
"""
from collections import defaultdict

from . import cuts, redundancy
from .queries import Q_COMPLEX_PLATFORMS, Q_COMPLEX_STREETS, Q_LIFT_COMPLEXES

EXACT_MAX = 10


class PlatformAccess:
    """Counts platform-directions with step-free access, in the complexes of the given lifts, for any closed set."""

    def __init__(self, base_graph, facilities):
        cxs = base_graph.ro_query(Q_LIFT_COMPLEXES, {"fids": sorted(facilities)}).result_set[0][0] if facilities else []
        self.dirs = []          # (edges, by_facility, sources, sinks)
        for cx in sorted(cxs):
            edges, lf = redundancy.complex_edges(base_graph, cx)
            by_fac = defaultdict(set)
            for eid, f in lf.items():
                by_fac[f].add(eid)
            streets = base_graph.ro_query(Q_COMPLEX_STREETS, {"cx": cx}).result_set[0][0]
            if not streets:
                continue
            for stop, uids, *_ in base_graph.ro_query(Q_COMPLEX_PLATFORMS, {"cx": cx}).result_set:
                for src, dst in ((streets, uids), (uids, streets)):
                    if cuts.connected(edges, src, dst):
                        self.dirs.append((edges, by_fac, src, dst))

    def ok(self, closed) -> int:
        n = 0
        for edges, by_fac, src, dst in self.dirs:
            skip = frozenset(e for f in closed for e in by_fac.get(f, ()))
            n += cuts.connected(edges, src, dst, skip)
        return n


def plan(net, closed, access: PlatformAccess, exact_max=EXACT_MAX) -> dict:
    lifts = sorted(set(closed))
    memo = {}

    def value(still_closed: frozenset):
        if still_closed not in memo:
            od = net.od(still_closed)
            memo[still_closed] = (sum(len(v) for v in od.values()), access.ok(still_closed))
        return memo[still_closed]

    def add(a, b):
        return (a[0] + b[0], a[1] + b[1])

    def steps(order):
        out, remaining = [], set(lifts)
        before = value(frozenset(remaining))
        area = (0, 0)
        for f in order:
            remaining.discard(f)
            after = value(frozenset(remaining))
            out.append({"facility_id": f, "journeys_restored": after[0] - before[0],
                        "platform_directions_restored": after[1] - before[1]})
            area = add(area, after)
            before = after
        return out, area

    # greedy: repair next whichever lift gives the best state now (ties: lowest id)
    remaining, greedy = set(lifts), []
    while remaining:
        f = max(sorted(remaining), key=lambda x: value(frozenset(remaining - {x})))
        greedy.append(f)
        remaining.discard(f)
    g_steps, g_area = steps(greedy)
    result = {"closed": lifts, "greedy": g_steps, "greedy_score": list(g_area),
              "start": list(value(frozenset(lifts))), "end": list(value(frozenset())), "exact": False}
    if len(lifts) <= exact_max:
        n = len(lifts)
        full = (1 << n) - 1
        best = {full: (0, 0)}
        choice = {}

        def still(mask):
            return frozenset(lifts[i] for i in range(n) if not mask >> i & 1)

        for mask in range(full - 1, -1, -1):           # supersets first: mask | bit > mask
            cands = []
            for i in range(n):
                if not mask >> i & 1:
                    nxt = mask | 1 << i
                    cands.append((add(value(still(nxt)), best[nxt]), -i, i))
            score, _, i = max(cands)
            best[mask], choice[mask] = score, i
        order, mask = [], 0
        while mask != full:
            i = choice[mask]
            order.append(lifts[i])
            mask |= 1 << i
        e_steps, e_area = steps(order)
        result.update(exact=True, order=e_steps, exact_score=list(e_area),
                      gap=[e_area[0] - g_area[0], e_area[1] - g_area[1]])
    else:
        result.update(order=g_steps, exact_score=None, gap=None)
    return result
