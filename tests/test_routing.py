"""Step-free routing and the station graph contraction, on the committed snapshot (no graph server)."""
import json
from pathlib import Path

import pytest

from lastlift.routing import Topology, describe, segments
from lastlift.station_view import contract, layers

ROOT = Path(__file__).resolve().parents[1]
SNAP = sorted(p for p in (ROOT / "data" / "snapshots").iterdir() if (p / "MANIFEST.json").is_file())[-1]
NODES = [json.loads(l) for l in (SNAP / "nodes.jsonl").read_text(encoding="utf-8").splitlines()]
EDGES = [json.loads(l) for l in (SNAP / "edges.jsonl").read_text(encoding="utf-8").splitlines()]
TOPO = Topology.from_rows(NODES, EDGES)
# Lifts closed in the frozen demo scope (modelled facilities of data/alerts/demo_closures.json).
DEMO = ["711", "777", "803", "854", "869", "876", "885", "961"]


def platform_uids(stop):
    return [n["uid"] for n in NODES if n.get("stop_id") == stop and "Node" in n["labels"]]


def lifts(path):
    return [e.facility_id for e in path if e.kind == "lift"]


def test_south_station_to_alewife_uses_813_and_814_with_961_closed():
    cost, path = TOPO.shortest(["street:place-sstat"], ["street:place-alfcl"], DEMO)
    assert {"813", "814"} <= set(lifts(path)) and "961" not in lifts(path)
    texts = [s["text"] for s in describe(TOPO, path)]
    assert any(t.startswith("ride Red to Alewife") for t in texts)


def test_closing_813_too_leaves_no_route_to_alewife():
    assert TOPO.shortest(["street:place-sstat"], ["street:place-alfcl"], DEMO + ["813"]) is None


def test_revere_beach_885_reroute_turns_around_at_wonderland_and_uses_884():
    cost, path = TOPO.shortest(platform_uids("70058"), ["street:place-rbmnl"], DEMO)
    assert lifts(path) == ["884"]
    steps = describe(TOPO, path)
    kinds = [s["kind"] for s in steps]
    assert kinds.index("ride") < kinds.index("turnaround") < kinds.index("lift")
    rides = [s for s in steps if s["kind"] == "ride"]
    assert rides[0]["text"] == "ride Blue to Wonderland" and rides[1]["back"] is True
    assert steps[0]["kind"] == "start" and steps[-1]["kind"] == "exit"


def test_ride_runs_never_hide_a_reversal():
    """No ride run visits the same station twice, so 'ride to X' can never hide a turnaround."""
    for stop in ("70058", "70057", "70061", "70038"):
        found = TOPO.shortest(platform_uids(stop), ["street:place-rbmnl", "street:place-alfcl", "street:place-sstat"])
        if not found:
            continue
        for kind, run in segments(found[1]):
            if kind == "ride":
                stops = [run[0].a] + [e.b for e in run]
                assert len(stops) == len(set(stops))


def test_backup_route_avoids_the_first_routes_lifts():
    cost, path = TOPO.shortest(["street:place-alfcl"], platform_uids("70061"), DEMO)
    first = set(lifts(path))
    backup = TOPO.shortest(["street:place-alfcl"], platform_uids("70061"), set(DEMO) | first)
    assert backup is None or not first & set(lifts(backup[1]))


def test_dijkstra_matches_networkx():
    nx = pytest.importorskip("networkx")
    g = nx.DiGraph()
    for e in EDGES:
        if e["type"] in ("SF", "RIDE") and not (e.get("kind") == "lift" and e.get("facility_id") in DEMO):
            g.add_edge(e["a"], e["b"], weight=e["wt"])
    for src, dst in (("street:place-sstat", "street:place-alfcl"), ("street:place-rbmnl", "street:place-sstat"),
                     ("street:place-chncl", "street:place-north"), ("street:place-forhl", "street:place-wondl")):
        ours = TOPO.shortest([src], [dst], DEMO)
        try:
            ref = nx.dijkstra_path_length(g, src, dst)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            ref = None
        assert (ours[0] if ours else None) == ref, (src, dst)


# --- station graph contraction ------------------------------------------------------------------
CX = {n["uid"]: n.get("cx") for n in NODES if "Node" in n["labels"]}


def complex_rows(cx):
    nodes = [{"uid": n["uid"], "labels": n["labels"], "name": n.get("name"), "platform_name": n.get("platform_name"),
              "facility_id": n.get("facility_id"), "unit": n.get("unit"), "closed": False,
              "stop_id": n.get("stop_id"), "wb": n.get("wheelchair_boarding")}
             for n in NODES if "Node" in n["labels"] and n.get("cx") == cx]
    edges = [{"eid": e["eid"], "a": e["a"], "b": e["b"], "type": e["type"], "kind": e.get("kind"),
              "facility_id": e.get("facility_id"), "pathway_ids": e.get("pathway_ids")}
             for e in EDGES if e["type"] in ("SF", "STEP") and CX.get(e["a"]) == cx]
    return nodes, edges


@pytest.mark.parametrize("cx", sorted({c for c in CX.values() if c}))
def test_contraction_keeps_every_node_and_ranks_all(cx):
    nodes, edges = complex_rows(cx)
    cn, ce, raw_map = contract(nodes, edges)
    assert sum(len(n["members"]) for n in cn.values()) == len(nodes)
    rank, band = layers(cn, ce)
    assert set(rank) == set(cn) == set(band)
    lifts_raw = {n["unit"] for n in nodes if "Lift" in n["labels"]}
    assert {c for c, n in cn.items() if n["kind"] == "lift"} == {f"lift:{u}" for u in lifts_raw}
    for e in ce.values():
        assert e["source"] in cn and e["target"] in cn and e["source"] != e["target"]
        assert e["kind"] in ("walk", "gate", "lift", "step")
        assert e["step_free"] == (e["kind"] != "step")


def test_contraction_ids_are_stable():
    nodes, edges = complex_rows("place-sstat")
    a = contract(nodes, edges)
    b = contract(list(reversed(nodes)), list(reversed(edges)))
    assert sorted(a[0]) == sorted(b[0]) and sorted(a[1]) == sorted(b[1])


def test_south_station_contracts_to_a_drawable_size():
    nodes, edges = complex_rows("place-sstat")
    cn, _, _ = contract(nodes, edges)
    assert len(cn) <= 80          # 193 raw nodes; 58 of the 75 are platforms, lifts, entrances, gates, street
