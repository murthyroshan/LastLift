"""M4 acceptance on a real graph server: closures, what-if, reroute, station contract, HTTP surface.
Seeds the base graph first if it is missing (CI starts from an empty FalkorDB)."""
import json

import pytest
from fastapi.testclient import TestClient

from lastlift import db, routing, seed, state, station_view, tools

pytestmark = pytest.mark.skipif(not db.ping(), reason="FalkorDB not reachable")
DEMO = ["711", "777", "803", "854", "869", "876", "885", "961"]


@pytest.fixture(scope="module", autouse=True)
def demo_scope():
    assert seed.main(["--if-missing"]) == 0
    tools.prepare_scope("demo")
    yield


def test_demo_scope_closes_exactly_the_frozen_modelled_lifts():
    assert state.closed(state.graph_name("demo")) == DEMO
    assert state.closed(state.graph_name("base")) == []


def test_alewife_hangs_on_813_while_961_is_closed():
    r = tools.platform_redundancy("place-alfcl")
    assert r["ok"]
    singles = [p for p in r["data"]["platforms"] if p.get("board", {}).get("k") == 1 or p.get("exit", {}).get("k") == 1]
    assert singles and all("813" in (p["board"]["last_lift"] + p["exit"]["last_lift"]) for p in singles)
    g = db.client().select_graph(state.graph_name("demo"))
    n = g.ro_query("MATCH (p:Platform {station_id:'place-alfcl'})-[:DEPENDS_NOW]->(l:Lift {facility_id:'813'}) "
                   "RETURN count(DISTINCT p)").result_set[0][0]
    assert n >= 1


def test_what_if_813_cuts_alewife_and_leaves_live_state_unchanged():
    before = state.closed(state.graph_name("demo"))
    r = tools.what_if_close(["813"])
    assert r["ok"] and any(p["station_id"] == "place-alfcl" for p in r["data"]["newly_lost"])
    copy = r["data"]["copy"]
    sim = routing.route(copy, state.graph_name("base"), ["street:place-sstat"], ["street:place-alfcl"], certify=False)
    assert sim["routes"] == []
    assert state.closed(state.graph_name("demo")) == before
    live = tools.step_free_route("place-sstat", "place-alfcl")
    assert live["data"]["routes"] and "813" in live["data"]["routes"][0]["lifts"]


def test_south_station_to_alewife_via_813_814_and_certified():
    r = tools.step_free_route("place-sstat", "place-alfcl")
    best = r["data"]["routes"][0]
    assert {"813", "814"} <= set(best["lifts"]) and "961" not in best["lifts"]
    assert best["certified"], best["certification"]
    assert r["evidence"]["ms"] < 15000


def test_route_certificate_rejects_a_route_through_a_closed_lift():
    topo = routing.topology(state.graph_name("base"))
    cost, path = topo.shortest(["street:place-alfcl"], [u for u in topo.nodes if u.split("#")[0] == "70061"])
    assert "961" in [e.facility_id for e in path if e.kind == "lift"]      # base route uses 961
    g = db.client().select_graph(state.graph_name("demo"))                # where 961 is closed
    cert = routing.certify_route(g, path)
    assert cert["status"] == "rejected" and any("lift:961" in m for m in cert["missing_or_closed"])
    assert routing.certify_route(db.client().select_graph(state.graph_name("base")), path)["status"] == "certified"


def test_revere_beach_885_reroutes_via_wonderland_and_884():
    r = tools.step_free_route("place-rbmnl", from_platform="70058")
    best = r["data"]["routes"][0]
    assert best["lifts"] == ["884"]
    assert [s for s in best["steps"] if s["kind"] == "turnaround"]
    assert "Wonderland" in r["summary"]


def test_unknown_station_is_not_invented():
    r = tools.step_free_route("place-nowhere", "place-alfcl")
    assert not r["ok"] and r["data"]["routes"] == []


STATIONS = ["place-alfcl", "place-sstat", "place-rbmnl", "place-chncl", "place-dwnxg"]


@pytest.mark.parametrize("sid", STATIONS)
@pytest.mark.parametrize("direction", ["board", "exit"])
def test_station_contract_schema(sid, direction):
    v = station_view.view(sid, direction)
    json.dumps(v)
    assert v["schema_version"] == station_view.SCHEMA_VERSION
    assert {"id", "name", "cx", "snapshot", "state_version", "closed"} <= v["station"].keys()
    ids = {n["id"] for n in v["nodes"]}
    assert len(ids) == len(v["nodes"])
    for n in v["nodes"]:
        assert n["kind"] in ("street", "entrance", "area", "gate", "lift", "platform")
        if n["kind"] == "lift":
            assert n["status"] in ("open", "closed", "sim_closed", "unknown")
    for e in v["edges"]:
        assert e["source"] in ids and e["target"] in ids and e["kind"] in ("walk", "gate", "lift", "step")
    eids = {e["id"] for e in v["edges"]}
    for r in v["routes"]:
        assert r["dir"] == direction and set(r["edge_ids"]) <= eids
    for p in v["platforms"]:
        assert {"id", "name", "k_board", "k_exit", "k_board_base", "k_exit_base", "cut_board", "cut_exit",
                "verdict", "assumptions"} <= p.keys()
    assert v["receipt"]["algo"] == "algo.maxFlow"


def test_station_contract_marks_simulated_closures():
    copy = tools.what_if_close(["813"])["data"]["copy"]
    v = station_view.view("place-alfcl", "exit", scenario=copy)
    status = {n.get("facility_id"): n["status"] for n in v["nodes"] if n["kind"] == "lift"}
    assert status["813"] == "sim_closed" and status["961"] == "closed"


# --- HTTP surface -------------------------------------------------------------------------------
client = TestClient(__import__("lastlift.main", fromlist=["app"]).app)


def test_http_tool_call_and_errors():
    assert {t["name"] for t in client.get("/v1/tools").json()} == set(tools.REGISTRY)
    r = client.post("/v1/tools/resolve_place", json={"query": "Alewife"})
    assert r.status_code == 200 and r.json()["ok"]
    assert client.post("/v1/tools/drop_graph", json={}).status_code == 404
    assert client.post("/v1/tools/resolve_place", json={"query": "x", "cypher": "MATCH (n) DELETE n"}).status_code == 422


def test_http_station_graph():
    assert client.get("/v1/stations/place-alfcl/graph", params={"dir": "exit"}).status_code == 200
    assert client.get("/v1/stations/place-nowhere/graph").status_code == 404
    assert client.get("/v1/stations/place-alfcl/graph", params={"scenario": "dev_ll_base"}).status_code == 404


def test_warm_fills_the_caches_the_slow_tools_read():
    from lastlift import network
    tools.warm(("demo",))
    net = network.get(state.graph_name("base"))
    key = (id(net), "n1", tuple(DEMO))
    assert key in network._results and (state.graph_name("demo"), tuple(DEMO)) in tools._ORDERS
    assert tools.network_impact(None, "demo")["ok"]
