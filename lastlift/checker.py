"""Independent proof checker for redundancy claims ("k lift-disjoint step-free routes").

It never computes a max-flow. Given the network, a claimed k, k paths and a claimed cut of lift
edges, it accepts only if all of these hold (Menger's theorem makes this a complete proof):
  * every path is a chain of real edges from a source to a sink,
  * no two paths share a lift edge,
  * there are exactly k paths and exactly k cut edges, all of them lift edges,
  * removing the cut edges leaves no route from any source to any sink.
k paths prove "at least k"; a k-edge cut proves "at most k". Together they prove exactly k.
"""
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class Verdict:
    accepted: bool
    reason: str = "ok"


def check(edges, lift_eids, sources, sinks, k, paths, cut):
    """edges: (eid, u, v, cap) tuples; lift_eids: ids of lift edges; paths: lists of edge ids."""
    by_id = {e[0]: e for e in edges}
    sources, sinks, lift_eids = set(sources), set(sinks), set(lift_eids)
    if len(paths) != k:
        return Verdict(False, f"{len(paths)} paths for claimed k={k}")
    if len(cut) != k:
        return Verdict(False, f"{len(cut)} cut edges for claimed k={k}")
    if any(eid not in lift_eids for eid in cut):
        return Verdict(False, "cut contains a non-lift edge")
    used_lifts = set()
    for i, path in enumerate(paths):
        if not path or any(eid not in by_id for eid in path):
            return Verdict(False, f"path {i} uses an unknown edge")
        if by_id[path[0]][1] not in sources or by_id[path[-1]][2] not in sinks:
            return Verdict(False, f"path {i} does not run source to sink")
        if any(by_id[a][2] != by_id[b][1] for a, b in zip(path, path[1:])):
            return Verdict(False, f"path {i} is not connected")
        lifts = [eid for eid in path if eid in lift_eids]
        if used_lifts & set(lifts):
            return Verdict(False, f"path {i} shares a lift with another path")
        used_lifts.update(lifts)
    blocked = set(cut)
    adj = defaultdict(list)
    for eid, u, v, _ in edges:
        if eid not in blocked:
            adj[u].append(v)
    seen, queue = set(sources), deque(sources)
    while queue:
        x = queue.popleft()
        for y in adj[x]:
            if y not in seen:
                seen.add(y)
                queue.append(y)
    if seen & sinks:
        return Verdict(False, "a route survives the claimed cut")
    return Verdict(True)
