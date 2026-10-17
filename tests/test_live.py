"""F10 live feed: MBTA alerts -> live graph sync, state_version, stale flag, failure handling, /v1/live."""
import httpx
import pytest
from fastapi.testclient import TestClient

from lastlift import alerts, db, live, seed, state, tools
from lastlift.main import app

needs_db = pytest.mark.skipif(not db.ping(), reason="FalkorDB not reachable")


def _body(*fids, other=("ESCALATOR", "9999")):
    """An MBTA alerts response: one elevator alert per facility id, plus an escalator alert that must be ignored."""
    data = [{"id": f"t{f}", "type": "alert", "attributes": {
        "effect": "ACCESS_ISSUE", "header": f"Elevator {f} unavailable", "updated_at": "2026-10-17T09:00:00-04:00",
        "active_period": [{"start": "2026-10-17T08:00:00-04:00", "end": None}],
        "informed_entity": [{"facility": f, "stop": "place-x", "activities": ["USING_WHEELCHAIR"]}]}} for f in fids]
    data.append({"id": "tesc", "type": "alert", "attributes": {
        "effect": "ESCALATOR_CLOSURE", "informed_entity": [{"facility": other[1]}]}})
    included = [{"id": f, "type": "facility", "attributes": {"type": "ELEVATOR"}} for f in fids]
    included.append({"id": other[1], "type": "facility", "attributes": {"type": other[0]}})
    return {"data": data, "included": included}


def test_closures_follow_the_facility_type_rule():
    cs = live.closures_from(_body("885", "876"), "2026-10-17T13:00:00+00:00")
    assert [c["facility_ids"] for c in cs] == [["876"], ["885"]] and cs[0]["stations"] == ["place-x"]


def test_feed_failure_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(live, "_status", {**live._status, "failures": 0, "last_ok_at": None})
    def down():
        raise httpx.ConnectError("no route")
    s = live.poll_once(down)
    assert s["failures"] == 1 and "ConnectError" in s["last_error"] and s["stale"] and s["source"] == "harvest"


@pytest.fixture
def live_graph():
    if not db.ping():
        pytest.skip("FalkorDB not reachable")
    assert seed.main(["--if-missing"]) == 0
    saved = dict(live._status)
    yield
    alerts._live = None                     # back to the committed harvest
    live._status.clear()
    live._status.update(saved)
    tools.prepare_scope("live")


@needs_db
def test_poll_syncs_the_live_graph_and_bumps_the_version(live_graph):
    v0 = live.status()["state_version"]
    s = live.poll_once(lambda: _body("885"))
    assert s["closed"] == ["885"] and s["state_version"] == v0 + 1 and not s["stale"] and s["source"] == "mbta_api"
    assert state.closed(state.graph_name("live")) == ["885"]
    cc = tools.current_closures(scope="live")
    assert [c["facility_ids"] for c in cc["data"]["closures"]] == [["885"]]
    assert live.poll_once(lambda: _body("885"))["state_version"] == v0 + 1      # same closed set: no bump
    s = live.poll_once(lambda: _body())
    assert s["closed"] == [] and s["changed"] == ["885"] and s["state_version"] == v0 + 2


@needs_db
def test_status_goes_stale_after_five_minutes(live_graph, monkeypatch):
    live.poll_once(lambda: _body())
    later = live._now() + __import__("datetime").timedelta(seconds=live.STALE_S + 1)
    monkeypatch.setattr(live, "_now", lambda: later)
    assert live.status()["stale"] is True


def test_live_endpoint_reports_the_feed():
    with TestClient(app) as c:
        r = c.get("/v1/live")
        assert r.status_code == 200 and {"feed", "stale", "state_version", "source", "age_s"} <= set(r.json())
