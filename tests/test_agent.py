"""M6: MCP contract, the agent reaches tools only through MCP, grounding, LLM-off and LLM-error fallbacks,
the frozen event schema, the HTTP endpoints, and replays that re-execute without drift."""
import ast
import asyncio
import json
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from lastlift import db, mcp_server, seed, tools
from lastlift.agent import grounding, llm, loop, replay
from lastlift.main import app

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts" / "ask_events.schema.json").read_text(encoding="utf-8"))
needs_db = pytest.mark.skipif(not db.ping(), reason="FalkorDB not reachable")


def run(coro):
    return asyncio.run(coro)


# --- no graph server needed ----------------------------------------------------------------------
def test_mcp_tools_equal_the_registry_and_are_read_only():
    async def listed():
        async with Client(mcp_server.mcp) as c:
            return await c.list_tools()
    ts = run(listed())
    assert {t.name for t in ts} == set(tools.REGISTRY)
    assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in ts)


def test_agent_code_never_imports_the_tool_registry():
    """The agent package may reach tools only through an MCP client: no import of lastlift.tools."""
    for path in (ROOT / "lastlift" / "agent").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                imported = {(node.module or "")} | {f"{node.module or ''}.{a.name}".strip(".") for a in node.names}
                assert not any(name.split(".")[-1] == "tools" for name in imported), f"{path.name} imports tools"
            if isinstance(node, ast.Import):
                assert not any(a.name.endswith("tools") for a in node.names), path.name


def test_grounding_rejects_a_fabricated_lift():
    results = [{"tool": "current_closures", "summary": "3 platforms lose step-free access",
                "data": {"closed": ["885", "876"]}, "entities": ["885", "876", "place-rbmnl"]}]
    assert grounding.check("Lift 885 at Revere Beach is closed.", results) == []
    problems = grounding.check("Lift 999 at Revere Beach is closed.", results)
    assert any("999" in p for p in problems)
    assert any("place-zzz" in p for p in grounding.check("See place-zzz.", results))
    assert any("G5" in p for p in grounding.check("Riders are stranded at Revere Beach.", results))
    assert grounding.check("Lift 885 is closed.", []) and "G1 no tool result" in grounding.check("x", [])
    timed = [{"summary": "best ~17.1 min", "data": {}, "entities": []}]
    assert grounding.check("It takes about 17 minutes.", timed) == []          # rounding is allowed
    assert any("G4" in p for p in grounding.check("It takes about 25 minutes.", timed))


def test_event_schema_is_valid_json_schema():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


# --- on a real graph server ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def graph():
    if not db.ping():
        pytest.skip("FalkorDB not reachable")
    assert seed.main(["--if-missing"]) == 0
    tools.prepare_scope("demo")


def _validate(events):
    v = jsonschema.Draft202012Validator(SCHEMA)
    for e in events:
        v.validate(e)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done" and "answer" in kinds
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))


@needs_db
def test_llm_off_answers_via_the_template(graph):
    r = run(loop.ask("Is Chinatown step-free right now?", mode="off"))
    assert r["source"] == "template" and "Chinatown" in r["answer"] and "Oak Grove" in r["answer"]
    _validate(r["events"])
    assert all(e["via"] == "mcp" for e in r["events"] if e["type"] == "tool_result")


@needs_db
def test_agent_cannot_bypass_mcp(graph, monkeypatch):
    """Break every direct path to the tools: the agent still answers, and every call went through MCP."""
    def broken(*a, **k):
        raise AssertionError("direct registry call")
    monkeypatch.setattr(tools, "REGISTRY", {name: broken for name in tools.REGISTRY})
    before = sum(mcp_server.CALLS.values())
    r = run(loop.ask("What happens if lift 813 fails too?", mode="off"))
    calls = [e for e in r["events"] if e["type"] == "tool_call"]
    assert calls and sum(mcp_server.CALLS.values()) - before == len(calls)
    assert "813" in r["answer"]


@needs_db
def test_fabricated_llm_answer_falls_back_to_the_template(graph, monkeypatch):
    replies = iter([
        {"content": "", "tool_calls": [{"id": "c1", "type": "function",
                                        "function": {"name": "current_closures", "arguments": "{}"}}]},
        {"content": "Lift 999 is closed and riders are stranded."},
    ])
    monkeypatch.setattr(llm, "chat", lambda *a, **k: next(replies))
    r = run(loop.ask("Which lifts are closed right now?", mode="live"))
    assert r["source"] == "template" and "999" not in r["answer"]
    g = next(e for e in r["events"] if e["type"] == "grounding")
    assert g["ok"] is False and any("999" in p for p in g["problems"])
    _validate(r["events"])


@needs_db
def test_llm_failure_falls_back_to_the_template(graph, monkeypatch):
    def down(*a, **k):
        raise llm.LLMError("LLM HTTP 429 (rate limit)")
    monkeypatch.setattr(llm, "chat", down)
    r = run(loop.ask("Which lifts should be repaired or protected first?", mode="live"))
    assert r["source"] == "template" and "854" in r["answer"]
    assert any(e["type"] == "error" and "429" in e["message"] for e in r["events"])


@needs_db
def test_unmodelled_lift_is_cannot_assess_not_no_effect(graph):
    r = run(loop.ask("Elevator 782 at Worcester is out. Who is affected?", mode="off"))
    assert "cannot assess" in r["answer"].lower()


@needs_db
def test_http_ask_post_and_sse(graph):
    with TestClient(app) as c:
        r = c.post("/api/ask", json={"question": "Is Chinatown step-free right now?"})
        assert r.status_code == 200 and r.json()["answer"]
        with c.stream("GET", "/api/ask", params={"q": "Which lifts are closed right now?"}) as s:
            kinds = [line.split(": ", 1)[1] for line in s.iter_lines() if line.startswith("event: ")]
        assert kinds[0] == "start" and kinds[-1] == "done" and "answer" in kinds
        assert c.post("/api/ask", json={"question": ""}).status_code == 400
        r = c.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"})
        assert r.status_code == 200 and "what_if_close" in r.text


def test_ask_fails_loudly_without_graph(monkeypatch):
    monkeypatch.setattr(db, "ping", lambda: False)
    with TestClient(app) as c:
        assert c.post("/api/ask", json={"question": "Is Chinatown step-free?"}).status_code == 503


REPLAYS = sorted(p.stem for p in replay.REPLAY_DIR.glob("*.json") if p.stem != "index")


@needs_db
@pytest.mark.parametrize("rid", REPLAYS)
def test_replay_reexecutes_without_drift(graph, rid):
    rec = replay.load(rid)
    _validate(rec["events"])
    assert run(replay.verify(rec, mcp_server.mcp)) == []


def test_seven_curated_replays_are_committed():
    index = json.loads((replay.REPLAY_DIR / "index.json").read_text(encoding="utf-8"))
    assert len(index) == 7 and {i["id"] for i in index} == set(REPLAYS)
