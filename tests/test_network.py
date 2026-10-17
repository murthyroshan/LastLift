"""M10 graph science: blast radius (dominators), all minimum cuts, N-2 pairs, reliability, N-1 table, repair order,
query plans. Each result is checked against an independent method, and where it matters against FalkorDB itself
(closures applied with Cypher on a private copy of the base graph, then FalkorDB's own max-flow or edges)."""
import collections
import itertools
import json
import os
import random

import pytest
from fastapi.testclient import TestClient

from lastlift import db, network, redundancy, seed, sequence, state, tools
from lastlift.cuts import Failures, all_min_cuts, brute_min_cuts, connected, monte_carlo, wilson
from lastlift.flow import exact_maxflow
from lastlift.queries import Q_CLOSE_LIFTS, Q_COMPLEX_PLATFORMS, Q_COMPLEX_STREETS, Q_REOPEN_LIFTS
from lastlift.routing import Topology

needs_db = pytest.mark.skipif(not db.ping(), reason="FalkorDB not reachable")
DOC = json.loads((seed.latest_snapshot() / "network.json").read_text(encoding="utf-8"))
CLAIMS = json.loads((seed.latest_snapshot().parents[2] / "claims.json").read_text(encoding="utf-8"))


# --- no graph server needed --------------------------------------------------------------------------------------
def _random_network(rng, n_lifts):
    """A node-split network like a station: levels joined by walkways (BIG) and lifts (capacity 1)."""
    big, edges, lf = 1_000_000, [], {}
    levels = [f"L{i}" for i in range(rng.randint(3, 6))]
    for i, (a, b) in enumerate(zip(levels, levels[1:])):
        if rng.random() < 0.3:
            edges.append((f"w{i}", a, b, big))
    for j in range(n_lifts):
        a, b = rng.sample(levels, 2)
        edges += [(f"in{j}", a, f"lift{j}", big), (f"lift{j}e", f"lift{j}", f"out{j}", 1), (f"o{j}", f"out{j}", b, big)]
        lf[f"lift{j}e"] = str(700 + j)
    return edges, lf, [levels[0]], [levels[-1]]


def test_all_min_cuts_equal_brute_force_on_random_networks():
    rng = random.Random(1017)
    checked = 0
    for _ in range(200):
        edges, lf, src, dst = _random_network(rng, rng.randint(2, 7))
        value, flow = exact_maxflow(edges, src, dst)
        if not 0 < value < 1_000_000:
            continue
        k = int(value)
        cuts, complete = all_min_cuts(edges, flow, src, dst, lf)
        assert complete and cuts == brute_min_cuts(edges, lf, src, dst, k)
        for c in cuts:                                       # closing any minimum cut leaves no route
            assert len(c) == k and not connected(edges, src, dst, frozenset(c))
        checked += 1
    assert checked > 50


def test_reliability_polynomial_limits_and_small_q():
    rng = random.Random(1018)
    for _ in range(60):
        edges, lf, src, dst = _random_network(rng, rng.randint(2, 6))
        value, flow = exact_maxflow(edges, src, dst)
        if not 0 < value < 1_000_000:
            continue
        f = Failures(edges, lf, src, dst)
        assert f.reliability(0.0) == 0 and abs(f.reliability(1.0) - 1) < 1e-12
        k = min(len(c) for c in f.minimal)
        assert f.counts[k] == sum(1 for c in f.minimal if len(c) == k)      # c_k = number of smallest failing sets
        q = 1e-4
        assert abs(f.reliability(q) / (f.counts[k] * q ** k) - 1) < 0.01  # R(q) ~ c_k q^k for small q


def test_network_numbers_agree_with_claims():
    lifts = DOC["lifts"]
    assert CLAIMS["net_spof_lifts"] == sum(1 for x in lifts.values() if x["od_cut"])
    assert CLAIMS["net_dominator_eq_witness"] == CLAIMS["net_dominator_lifts"] == len(lifts)
    assert CLAIMS["n2_critical_pairs"] == len(DOC["pairs"])
    assert CLAIMS["mincut_pq_eq_brute"] == CLAIMS["mincut_dirs"]
    assert CLAIMS["net_conditional_cross_station"] == sum(1 for c in DOC["conditional"] if not c["same_station"])
    for p in DOC["pairs"]:                                   # a pair: neither alone, both together
        for d in p["dirs"]:
            entry = DOC["platform"][d["stop_id"]][d["dir"]]
            assert [p["a"], p["b"]] in entry["minimal"]


# --- on the graph server --------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def base():
    if not db.ping():
        pytest.skip("FalkorDB not reachable")
    assert seed.main(["--if-missing"]) == 0
    return state.graph_name("base")


@pytest.fixture(scope="module")
def sandbox(base):
    """A private copy of the base graph; closures are applied to it with the app's own Cypher."""
    name = state.graph_name(f"wi_test_net_{os.getpid()}")
    if state.exists(name):
        db.client().select_graph(name).delete()
    db.client().connection.execute_command("GRAPH.COPY", base, name)
    yield db.client().select_graph(name)
    if state.exists(name):                  # the API's boot sweep may already have removed it
        db.client().select_graph(name).delete()


def _close(g, fids):
    g.query(Q_REOPEN_LIFTS, {"fids": []})
    if fids:
        g.query(Q_CLOSE_LIFTS, {"fids": list(fids)})


@needs_db
def test_dominator_prediction_equals_falkordb_state(base, sandbox):
    """For every network single point of failure and 20 random other lifts: close it in FalkorDB (Cypher type swap
    on a copy), read the copy's open edges back, search: the journeys lost equal the dominator prediction."""
    net = network.get(base)
    spof = sorted(f for f, x in DOC["lifts"].items() if x["od_cut"])
    others = random.Random(1019).sample(sorted(set(DOC["lifts"]) - set(spof)), 20)
    base_od = net.od(zones=False)
    pred = net.n1()
    try:
        for f in spof + others:
            _close(sandbox, [f])
            after = network.Net(Topology.from_graph(sandbox)).od(zones=False)
            lost = {(a, b) for a in base_od for b in base_od[a] - after[a]}
            assert lost == pred[f].broken, f
    finally:
        _close(sandbox, [])


@needs_db
def test_critical_pairs_cut_access_in_falkordb(base, sandbox):
    """Each N-2 pair: FalkorDB's certified max-flow is 0 for its platform-directions with both closed, and > 0
    with either one closed alone."""
    streets = {}
    by_cx = collections.defaultdict(list)
    for p in DOC["pairs"]:
        cx = DOC["platform"][p["dirs"][0]["stop_id"]]["cx"]
        by_cx[cx].append(p)
    try:
        for cx, pairs in sorted(by_cx.items()):
            streets[cx] = sandbox.ro_query(Q_COMPLEX_STREETS, {"cx": cx}).result_set[0][0]
            uids = {r[0]: r[1] for r in sandbox.ro_query(Q_COMPLEX_PLATFORMS, {"cx": cx}).result_set}
            for p in pairs:
                for closed, want_zero in (([p["a"], p["b"]], True), ([p["a"]], False), ([p["b"]], False)):
                    _close(sandbox, closed)
                    edges, lf = redundancy.complex_edges(sandbox, cx)
                    for d in p["dirs"]:
                        src, dst = ((streets[cx], uids[d["stop_id"]]) if d["dir"] == "board"
                                    else (uids[d["stop_id"]], streets[cx]))
                        k = redundancy.direction(sandbox, edges, lf, src, dst).k
                        assert (k == 0) == want_zero, (p["a"], p["b"], closed, d)
    finally:
        _close(sandbox, [])


@needs_db
def test_single_lift_table_equals_falkordb_on_five_stations(base, sandbox):
    """The per-lift N-1 table (k with each lift closed) equals FalkorDB's certified max-flow, every cell."""
    picks = ["place-harsq", "place-alfcl", "place-rbmnl", "place-chncl", "place-kencl"]
    cells = 0
    try:
        for sid in picks:
            plats = {s: p for s, p in DOC["platform"].items() if p["station_id"] == sid}
            cx = next(iter(plats.values()))["cx"]
            streets = sandbox.ro_query(Q_COMPLEX_STREETS, {"cx": cx}).result_set[0][0]
            uids = {r[0]: r[1] for r in sandbox.ro_query(Q_COMPLEX_PLATFORMS, {"cx": cx}).result_set}
            for f in DOC["n1"][cx]["facilities"]:
                _close(sandbox, [f])
                edges, lf = redundancy.complex_edges(sandbox, cx)
                for stop, p in plats.items():
                    for d in ("board", "exit"):
                        e = p[d]
                        if e.get("at_grade") or not e.get("k"):
                            continue
                        src, dst = (streets, uids[stop]) if d == "board" else (uids[stop], streets)
                        k = redundancy.direction(sandbox, edges, lf, src, dst).k
                        assert k == e["k_without"].get(f, e["k"]), (sid, stop, d, f)
                        cells += 1
    finally:
        _close(sandbox, [])
    assert cells > 20


@needs_db
def test_all_min_cuts_equal_brute_force_on_real_stations(base):
    g = db.client().select_graph(base)
    for sid in ("place-harsq", "place-alfcl", "place-sstat", "place-tumnl", "place-gover"):
        plats = {s: p for s, p in DOC["platform"].items() if p["station_id"] == sid}
        cx = next(iter(plats.values()))["cx"]
        edges, lf = redundancy.complex_edges(g, cx)
        streets = g.ro_query(Q_COMPLEX_STREETS, {"cx": cx}).result_set[0][0]
        uids = {r[0]: r[1] for r in g.ro_query(Q_COMPLEX_PLATFORMS, {"cx": cx}).result_set}
        for stop, p in plats.items():
            for d in ("board", "exit"):
                if not p[d].get("k") or p[d].get("at_grade"):
                    continue
                src, dst = (streets, uids[stop]) if d == "board" else (uids[stop], streets)
                value, flow = exact_maxflow(edges, src, dst)
                cuts, _ = all_min_cuts(edges, flow, src, dst, lf)
                assert cuts == brute_min_cuts(edges, lf, src, dst, int(value))


@needs_db
def test_reliability_matches_monte_carlo_on_twenty_platforms(base):
    g = db.client().select_graph(base)
    rng = random.Random(1020)
    rows = sorted((s, d) for s, p in DOC["platform"].items() for d in ("board", "exit") if p[d].get("rel_counts"))
    for stop, d in rng.sample(rows, 20):
        p = DOC["platform"][stop]
        edges, lf = redundancy.complex_edges(g, p["cx"])
        streets = g.ro_query(Q_COMPLEX_STREETS, {"cx": p["cx"]}).result_set[0][0]
        uids = {r[0]: r[1] for r in g.ro_query(Q_COMPLEX_PLATFORMS, {"cx": p["cx"]}).result_set}
        src, dst = (streets, uids[stop]) if d == "board" else (uids[stop], streets)
        f = Failures(edges, lf, src, dst)
        assert f.counts == p[d]["rel_counts"]
        q = 0.15
        _, (lo, hi) = monte_carlo(f, edges, lf, src, dst, q, 3000, rng)
        mc_fail = monte_carlo(f, edges, lf, src, dst, q, 3000, random.Random(stop))[0]
        lo, hi = wilson(round(mc_fail * 3000), 3000, z=3.29)
        assert lo <= f.reliability(q) <= hi, (stop, d)


@needs_db
def test_repair_order_exact_beats_or_ties_greedy_and_every_permutation(base):
    net = network.get(base)
    closed = state.closed(tools._scope_graph("demo"))[:5]
    access = sequence.PlatformAccess(db.client().select_graph(base), closed)
    plan = sequence.plan(net, closed, access)
    assert plan["exact"] and tuple(plan["exact_score"]) >= tuple(plan["greedy_score"])
    best = None
    for perm in itertools.permutations(closed):          # the dynamic programme equals trying every order
        remaining, score = set(closed), (0, 0)
        for f in perm:
            remaining.discard(f)
            od = net.od(remaining)
            v = (sum(len(x) for x in od.values()), access.ok(remaining))
            score = (score[0] + v[0], score[1] + v[1])
        best = score if best is None or score > best else best
    assert tuple(plan["exact_score"]) == best


@needs_db
def test_network_impact_tool(base):
    tools.prepare_scope("demo")
    r = tools.network_impact(["884"], scope="demo")
    assert r["ok"] and "place-rbmnl" in r["data"]["cut_off"] and r["data"]["journeys_broken"] > 0
    now = tools.network_impact(scope="demo")
    assert any(x["facility_id"] == "884" for x in now["data"]["last_link"])     # 885 is closed in the demo
    assert not tools.network_impact(["99999"], scope="demo")["ok"]


@needs_db
def test_query_plans_refuse_writes_and_are_rate_limited(base):
    from lastlift import main
    with TestClient(main.app) as c:
        main._PLAN_CALLS.clear()
        assert c.get("/v1/queries/Q_CLOSE_LIFTS/plan").status_code == 403
        assert c.get("/v1/queries/Q_NOPE/plan").status_code == 404
        r = c.get("/v1/queries/Q_MAXFLOW/plan")
        assert r.status_code == 200 and any("ProcedureCall" in line for line in r.json()["plan"])
        r = c.get("/v1/queries/Q_LOST_NOW/plan", params={"mode": "profile"})
        assert r.status_code == 200 and "Records produced" in r.json()["plan"][0]
        codes = [c.get("/v1/queries/Q_META/plan").status_code for _ in range(10)]
        assert codes[-1] == 429
        main._PLAN_CALLS.clear()
