"""M14 CERT-4: "Re-check in FalkorDB" closes a platform-direction's minimum cut on a throwaway copy and runs the
certified max-flow: it must return 0 for every lift-dependent platform-direction tried (and never touch the scope)."""
import json

import pytest
from fastapi.testclient import TestClient

from lastlift import db, seed, state, tools
from lastlift.main import app

pytestmark = pytest.mark.skipif(not db.ping(), reason="FalkorDB not reachable")
NET = json.loads((seed.latest_snapshot() / "network.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("stop,d", [("70061", "exit"), ("70058", "board"), ("70018", "exit"), ("70019", "board")])
def test_recheck_closes_the_cut_and_finds_no_route(stop, d):
    tools.prepare_scope("demo")
    p = NET["platform"][stop]
    cut = p[d]["mincuts"][0]
    before = state.closed(state.graph_name("demo"))
    with TestClient(app) as c:
        r = c.post("/v1/verify-cut", json={"station_id": p["station_id"], "stop_id": stop, "dir": d, "cut": cut})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["max_flow"] == 0 and body["graph"].startswith(state.graph_name("wi_"))
        assert c.post("/v1/verify-cut", json={"stop_id": stop, "dir": "up", "cut": cut}).status_code == 400
    assert state.closed(state.graph_name("demo")) == before
