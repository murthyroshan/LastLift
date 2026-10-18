"""Health endpoints: /healthz is fast and honest; /v1/health reports FalkorDB reachability."""
from fastapi.testclient import TestClient

from lastlift import db
from lastlift.main import app

client = TestClient(app)


def test_healthz_reflects_graph_server():
    r = client.get("/healthz")
    if db.ping():
        assert r.status_code == 200 and r.json()["status"] == "ok"
    else:
        assert r.status_code == 503


def test_healthz_answers_head_for_uptime_monitors():
    assert client.head("/healthz").status_code == (200 if db.ping() else 503)


def test_v1_health_shape():
    body = client.get("/v1/health").json()
    assert {"status", "version", "falkordb", "llm_mode", "actions_mode", "uptime_s"} <= body.keys()
    if body["falkordb"]["reachable"]:
        assert body["falkordb"]["module_version"].startswith("4.22")


def test_healthz_degrades_when_graph_server_is_off(monkeypatch):
    monkeypatch.setattr(db, "ping", lambda: False)
    r = client.get("/healthz")
    assert r.status_code == 503 and r.json()["status"] == "degraded"
