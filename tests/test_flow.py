"""Certification, exact repair, min-cut and the independent proof checker."""
import random

import networkx as nx
import pytest

from lastlift import db
from lastlift.checker import check
from lastlift.flow import certify, decompose, exact_maxflow, min_cut, repair

BIG = 1_000_000
# Chokepoint's 11-edge node-split repro: true max-flow 453; FalkorDB 4.22.0 returns 300.
REPRO = [("e1", "src:out", "a15:in", 3322), ("e2", "a15:in", "a15:out", 158), ("e3", "a15:out", "a20:in", 3322),
         ("e4", "src:out", "a20:in", 3322), ("e5", "a20:in", "a20:out", 300), ("e6", "a20:out", "x1:in", 3322),
         ("e7", "a15:out", "a3:in", 3322), ("e8", "a3:in", "a3:out", 153), ("e9", "a3:out", "a12:in", 3322),
         ("e10", "a12:in", "a12:out", 261), ("e11", "a12:out", "x1:in", 3322)]


def nx_value(edges, sources, sinks):
    g = nx.DiGraph()
    for eid, u, v, cap in edges:
        g.add_edge(u, v, capacity=cap)
    for s in sources:
        g.add_edge("__S", s, capacity=float("inf"))
    for t in sinks:
        g.add_edge(t, "__T", capacity=float("inf"))
    return nx.maximum_flow_value(g, "__S", "__T")


def lift_net(rng):
    """Random station-shaped network: lifts are capacity-1 edges, walkways BIG, no parallel edges."""
    nodes = [f"n{i}" for i in range(rng.randint(6, 14))]
    edges, seen = [], set()

    def add(eid, u, v, c):
        if u != v and (u, v) not in seen:
            seen.add((u, v))
            edges.append((eid, u, v, c))

    for i in range(rng.randint(8, 22)):
        add(f"p{i}", *rng.sample(nodes, 2), BIG)
    lifts = []
    for j in range(rng.randint(2, 6)):
        a, b = rng.sample(nodes, 2)
        add(f"a{j}", a, f"L{j}", BIG)
        add(f"lift{j}", f"L{j}", f"L{j}:out", 1)
        add(f"b{j}", f"L{j}:out", b, BIG)
        lifts.append(f"lift{j}")
    sources = rng.sample(nodes, rng.randint(1, 3))
    sink = rng.choice([n for n in nodes if n not in sources])
    return edges, lifts, sources, [sink]


def test_certificate_rejects_the_known_falkordb_answer():
    """FalkorDB's flow on the repro carries only the 300-unit route; it must not certify."""
    falkordb_flow = {"e4": 300, "e5": 300, "e6": 300}
    cert = certify(REPRO, falkordb_flow, ["src:out"], ["x1:in"])
    assert cert.feasible and not cert.maximal
    value, _, outcome = repair(REPRO, falkordb_flow, ["src:out"], ["x1:in"])
    assert (value, outcome) == (453, "repaired")


def test_exact_solver_matches_networkx_on_random_networks():
    rng = random.Random(42)
    for _ in range(200):
        edges, _, src, dst = lift_net(rng)
        value, flow = exact_maxflow(edges, src, dst)
        assert value == nx_value(edges, src, dst)
        assert certify(edges, flow, src, dst).ok


def test_checker_accepts_true_proofs_and_rejects_every_mutant():
    rng = random.Random(7)
    tested = mutants = 0
    for _ in range(1500):
        edges, lifts, src, dst = lift_net(rng)
        value, flow = exact_maxflow(edges, src, dst)
        k = int(value)
        if not 0 < k < BIG:
            continue
        cut = [e[0] for e in min_cut(edges, flow, src)]
        paths = decompose(edges, flow, src, dst)
        assert check(edges, lifts, src, dst, k, paths, cut).accepted
        tested += 1
        bad = [
            (k + 1, paths, cut),                          # inflated k
            (k, paths[:-1], cut),                         # a route dropped
            (k, paths, cut[:-1] + ["p0"]),                # a walkway put in the cut
        ]
        if len(paths) >= 2:
            bad.append((k, [paths[0], paths[0]] + paths[2:], cut))  # duplicated route
        for kk, pp, cc in bad:
            mutants += 1
            assert not check(edges, lifts, src, dst, kk, pp, cc).accepted
        # Swapping a cut lift for another lift is only wrong if routes survive the new cut
        # (two lifts in series are both valid single cuts). Ground truth decides.
        for other in (l for l in lifts if l not in cut):
            swapped = cut[:-1] + [other]
            still_blocks = exact_maxflow([e for e in edges if e[0] not in swapped], src, dst)[0] == 0
            assert check(edges, lifts, src, dst, k, paths, swapped).accepted == still_blocks
            mutants += not still_blocks
    assert tested >= 50 and mutants >= 150


@pytest.mark.skipif(not db.ping(), reason="FalkorDB not reachable")
@pytest.mark.xfail(strict=True, reason="FalkorDB 4.22 algo.maxFlow returns 300 on this repro; a fix would make this pass")
def test_falkordb_maxflow_on_known_repro():
    name = "test_ll_repro"
    client = db.client()
    if name in client.list_graphs():
        client.select_graph(name).delete()
    g = client.select_graph(name)
    try:
        ids = sorted({u for _, u, _, _ in REPRO} | {v for _, _, v, _ in REPRO})
        g.query("UNWIND $ids AS i CREATE (:N {id:i})", {"ids": ids})
        g.query("UNWIND $rows AS r MATCH (a:N {id:r.u}), (b:N {id:r.v}) CREATE (a)-[:E {cap:r.c}]->(b)",
                {"rows": [{"u": u, "v": v, "c": c} for _, u, v, c in REPRO]})
        mf = g.ro_query("MATCH (s:N {id:'src:out'}), (t:N {id:'x1:in'}) CALL algo.maxFlow({sourceNodes:[s], "
                        "targetNodes:[t], relationshipTypes:['E'], capacityProperty:'cap'}) YIELD maxFlow "
                        "RETURN maxFlow").result_set[0][0]
        assert mf == 453
    finally:
        g.delete()
