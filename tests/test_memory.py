"""M5: fail loudly without the graph, incident memory, priority tie-break, eval reproducibility."""
import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from lastlift import alerts, db, incidents, seed, tools, verdict
from lastlift.main import app

ROOT = Path(__file__).resolve().parents[1]
http = TestClient(app)


# --- fail loudly ----------------------------------------------------------------------------------
class _Down:
    def __getattr__(self, name):
        raise RedisConnectionError("graph server down (test)")


ARGS = {"resolve_place": {"query": "Alewife"}, "current_closures": {}, "platform_redundancy": {"station_id": "place-alfcl"},
        "what_if_close": {"facility_ids": ["813"]}, "step_free_route": {"from_station": "place-sstat", "to_station": "place-alfcl"},
        "repair_priority": {}, "lift_history": {"facility_id": "961"}, "draft_action": {"facility_id": "813"},
        "network_impact": {"facility_ids": ["884"]}, "repair_order": {}, "recall_lift_history": {"facility_id": "885"},
        "lift_dossier": {"facility_id": "813"}, "stress_test": {"budget": 2}}


def test_every_tool_is_covered():
    assert set(ARGS) == set(tools.REGISTRY)


@pytest.mark.parametrize("name", sorted(ARGS))
def test_fails_loudly_without_graph(monkeypatch, name):
    monkeypatch.setattr(db, "client", lambda: _Down())
    monkeypatch.setattr(tools.routing, "_topo", {})
    r = http.post(f"/v1/tools/{name}", json=ARGS[name])
    assert r.status_code == 503
    body = r.json()
    assert body["ok"] is False and body["error"] == "graph_unavailable" and body["data"] is None


def test_station_graph_fails_loudly_without_graph(monkeypatch):
    monkeypatch.setattr(db, "client", lambda: _Down())
    assert http.get("/v1/stations/place-alfcl/graph").status_code == 503


# --- priority tie-break (no graph needed) ---------------------------------------------------------
def test_lift_closed_more_often_ranks_above_an_otherwise_equal_lift():
    a = {"facility_id": "100", "tier": 3, "newly_last": 0, "departures_day": 50, "incidents": 0}
    b = {"facility_id": "999", "tier": 3, "newly_last": 0, "departures_day": 50, "incidents": 2}
    assert [r["facility_id"] for r in tools.rank([a, b])] == ["999", "100"]
    c = {"facility_id": "500", "tier": 2, "newly_last": 1, "departures_day": 0, "incidents": 0}
    assert tools.rank([a, b, c])[0]["facility_id"] == "500"       # tier first: memory only breaks ties


# --- on a real graph server -----------------------------------------------------------------------
needs_db = pytest.mark.skipif(not db.ping(), reason="FalkorDB not reachable")


@pytest.fixture(scope="module")
def scopes():
    assert seed.main(["--if-missing"]) == 0
    tools.prepare_scope("demo")
    incidents.sync("base")


@needs_db
def test_incident_memory_frozen_in_demo_and_current_in_base(scopes):
    demo = tools.lift_history("961", "demo")["data"]["incidents"]
    assert len(demo) == 1 and demo[0]["ongoing"] is True and demo[0]["alert_id"] == "1038975"
    base = tools.lift_history("961", "base")["data"]["incidents"]
    activity = alerts.activity()["alerts"]["1038975"]
    assert base[0]["ongoing"] is (activity["last_active"] >= alerts.activity()["last_poll"])
    if not base[0]["ongoing"]:
        assert base[0]["ended_by"] == activity["first_absent"]
    assert tools.lift_history("813", "demo")["data"]["incidents"] == []


@needs_db
def test_priority_tiers_in_demo(scopes):
    ranked = tools.repair_priority("demo", limit=200)["data"]["ranked"]
    tiers = {t: {r["facility_id"] for r in ranked if r["tier"] == t} for t in (1, 2)}
    assert tiers[1] == {"854", "876", "885"}
    assert tiers[2] == {"813", "891", "866"}
    assert [r["tier"] for r in ranked] == sorted(r["tier"] for r in ranked)


@needs_db
@pytest.mark.parametrize("fids", [["782"], ["704"], ["751"], ["726"], ["929", "930"], ["subplat-cenav-1"]])
def test_model_abstains_where_there_is_no_layout_data(scopes, fids):
    assert verdict.assess(fids)["verdict"] == "CANNOT_ASSESS"


@needs_db
@pytest.mark.parametrize("gold_id", ["L04", "L09", "L12", "L14"])
def test_committed_eval_reproduces(scopes, gold_id):
    row = next(r for r in csv.DictReader((ROOT / "validation" / "eval_live.csv").open(encoding="utf-8"))
               if r["gold_id"] == gold_id)
    v = verdict.assess(row["facility_ids"].split(";"))
    assert v["verdict"] == row["model_verdict"]
    assert ";".join(v["entrances_cut"]) == row["model_entrances_cut"]
