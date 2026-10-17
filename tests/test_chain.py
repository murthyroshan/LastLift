"""F11 provider chain (fault injection at the HTTP layer), the daily token budget, and A10 W3C trace ids."""
import asyncio
import dataclasses

import httpx
import pytest
from fastapi.testclient import TestClient

from lastlift import db, seed, tools
from lastlift.agent import llm, loop
from lastlift.main import app

needs_db = pytest.mark.skipif(not db.ping(), reason="FalkorDB not reachable")
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT = "00f067aa0ba902b7"


def _reply(content="", tool_calls=None, tokens=(100, 20)):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return httpx.Response(200, json={"model": "m", "choices": [{"message": msg}],
                                     "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1],
                                               "total_tokens": sum(tokens)}})


@pytest.fixture(scope="module")
def graph():
    if not db.ping():
        pytest.skip("FalkorDB not reachable")
    assert seed.main(["--if-missing"]) == 0
    tools.prepare_scope("demo")


@pytest.fixture
def fake(monkeypatch):
    """Keys present, a fresh budget, and an httpx.post that answers per model from a script."""
    monkeypatch.setattr(llm, "settings", dataclasses.replace(
        llm.settings, groq_api_key="k1", gemini_api_key="k2", llm_daily_token_budget=10_000))
    monkeypatch.setattr(llm, "_usage", {"day": None, "tokens": 0})
    seen = []
    script = {}

    def post(url, json, timeout, headers):
        seen.append(json["model"])
        out = script[json["model"]]
        return out.pop(0) if isinstance(out, list) else out
    monkeypatch.setattr(llm.httpx, "post", post)
    return script, seen


def test_chain_order_is_qwen_gpt_oss_gemini():
    assert [t.model for t in llm.tiers()] == [llm.settings.groq_model, llm.settings.groq_fallback_model,
                                              llm.settings.gemini_chat_model]
    assert llm.tiers()[2].url.startswith("https://generativelanguage.googleapis.com/")


def test_rate_limit_and_server_error_fail_over_to_gemini(fake):
    script, seen = fake
    s = llm.settings
    script[s.groq_model] = httpx.Response(429, text="org_secret details")
    script[s.groq_fallback_model] = httpx.Response(503)
    script[s.gemini_chat_model] = _reply("ok")
    chain = llm.Chain()
    msg = llm.chat([{"role": "user", "content": "q"}], chain=chain)
    assert msg["content"] == "ok" and msg["model"] == s.gemini_chat_model
    assert seen == [s.groq_model, s.groq_fallback_model, s.gemini_chat_model]
    assert [(f["from_model"], f["to_model"]) for f in chain.failovers] == [
        (s.groq_model, s.groq_fallback_model), (s.groq_fallback_model, s.gemini_chat_model)]
    assert not any("org_secret" in f["message"] for f in chain.failovers)      # provider bodies never echoed
    # a failed tier stays skipped for the rest of the question
    script[s.gemini_chat_model] = _reply("again")
    assert chain.chat([{"role": "user", "content": "q"}])["content"] == "again" and seen[-1] == s.gemini_chat_model


def test_timeout_and_every_tier_down_raise_for_the_template(fake, monkeypatch):
    def down(*a, **k):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(llm.httpx, "post", down)
    chain = llm.Chain()
    with pytest.raises(llm.LLMError):
        chain.chat([{"role": "user", "content": "q"}])
    assert chain.failovers[-1]["to_model"] == "template" and len(chain.failovers) == 3


def test_token_budget_counts_usage_and_stops_the_chain(fake, monkeypatch):
    script, seen = fake
    monkeypatch.setattr(llm, "settings", dataclasses.replace(llm.settings, llm_daily_token_budget=150))
    script[llm.settings.groq_model] = [_reply("one", tokens=(100, 60)), _reply("two")]
    chain = llm.Chain()
    chain.chat([{"role": "user", "content": "q"}])
    assert llm.tokens_used_today() == 160 and llm.budget_left() == 0
    with pytest.raises(llm.LLMError):
        chain.chat([{"role": "user", "content": "q"}])
    assert len(seen) == 1 and "budget" in chain.failovers[0]["message"]         # no further request is sent


def test_traceparent_is_joined_or_a_new_trace_is_made():
    assert loop.parse_traceparent(f"00-{TRACE}-{PARENT}-01") == (TRACE, PARENT)
    for bad in (None, "", "garbage", f"00-{'0' * 32}-{PARENT}-01", f"00-{TRACE}-{'0' * 16}-01"):
        tid, parent = loop.parse_traceparent(bad)
        assert len(tid) == 32 and tid != "0" * 32 and parent is None


@needs_db
def test_agent_fails_over_visibly_and_records_the_serving_model(graph, fake):
    script, _ = fake
    s = llm.settings
    script[s.groq_model] = httpx.Response(429)
    script[s.groq_fallback_model] = httpx.Response(500)
    call = [{"id": "c1", "type": "function", "function": {"name": "current_closures", "arguments": "{}"}}]
    script[s.gemini_chat_model] = [_reply(tool_calls=call),
                                   _reply("Some lifts are closed in the open-data model. Check mbta.com/alerts/access.")]
    r = asyncio.run(loop.ask("Which lifts are closed right now?", mode="live",
                             traceparent=f"00-{TRACE}-{PARENT}-01"))
    fo = [e for e in r["events"] if e["type"] == "error" and e["stage"] == "llm_failover"]
    assert [e["to_model"] for e in fo] == [s.groq_fallback_model, s.gemini_chat_model]
    ans = next(e for e in r["events"] if e["type"] == "answer")
    assert r["source"] == "llm" and ans["model"] == s.gemini_chat_model and ans["usage"]["input_tokens"] == 200
    start = r["events"][0]
    assert start["trace_id"] == TRACE == r["trace_id"] and start["parent_span_id"] == PARENT
    tc = next(e for e in r["events"] if e["type"] == "tool_call")
    tr = next(e for e in r["events"] if e["type"] == "tool_result")
    assert tc["span_id"] == tr["span_id"] != start["span_id"]


@needs_db
def test_http_ask_returns_the_trace_id(graph):
    with TestClient(app) as c:
        r = c.post("/api/ask", json={"question": "Is Chinatown step-free right now?"},
                   headers={"traceparent": f"00-{TRACE}-{PARENT}-01"})
        assert r.status_code == 200 and r.json()["trace_id"] == TRACE
