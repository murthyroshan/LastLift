"""M13 A3: memory and provenance in the graph. A chat run records what it read; closing and reopening a lift marks
stale only the answers that read it; recall and the dossier read it back; disagreements are seeded from validation."""
import asyncio

import pytest

from lastlift import db, seed, state, tools
from lastlift.agent import loop

pytestmark = pytest.mark.skipif(not db.ping(), reason="FalkorDB not reachable")


@pytest.fixture(scope="module")
def demo():
    assert seed.main(["--if-missing"]) == 0
    tools.prepare_scope("demo")
    g = db.client().select_graph(state.graph_name("demo"))
    g.query("MATCH (n) WHERE n:Run OR n:ToolCall OR n:Answer DETACH DELETE n")
    return g


def answers(g):
    return {r[0]: (r[1], r[2]) for r in g.ro_query("MATCH (a:Answer) RETURN a.question, a.stale, a.stale_reason").result_set}


def test_a_lift_changing_state_makes_only_the_answers_that_read_it_stale(demo):
    asyncio.run(loop.ask("Which lift at Alewife is now the last one?", mode="off"))
    asyncio.run(loop.ask("Is Chinatown step-free right now?", mode="off"))
    before = answers(demo)
    assert len(before) == 2 and not any(s for s, _ in before.values())
    name = state.graph_name("demo")
    closed = state.closed(name)
    try:
        state.sync(name, closed + ["813"])          # 813 closes: the Alewife answer read it, Chinatown's did not
        state.sync(name, closed)                    # and reopens
    finally:
        state.sync(name, closed)
    after = answers(demo)
    assert after["Which lift at Alewife is now the last one?"][0] is True
    assert "813" in after["Which lift at Alewife is now the last one?"][1]
    assert after["Is Chinatown step-free right now?"][0] is False


def test_runs_record_their_tool_calls_and_reads(demo):
    rows = demo.ro_query("MATCH (r:Run)-[c:CALLED]->(t:ToolCall)-[:READ]->(x) "
                         "RETURN r.client, t.tool, count(DISTINCT x)").result_set
    assert rows and all(r[0] == "lastlift-chat" for r in rows) and any(r[2] > 0 for r in rows)


def test_recall_and_dossier_read_the_memory(demo):
    r = tools.recall_lift_history("885", "demo")
    assert r["ok"] and "not a forecast" in r["summary"] and r["data"]["history"]["incidents"]
    d = tools.lift_dossier("813", "demo")
    assert d["ok"] and "# Lift 813" in d["data"]["markdown"]
    assert not tools.lift_dossier("99999", "demo")["ok"]


def test_disagreements_lower_confidence_in_recall(demo):
    r = tools.recall_lift_history("803", "demo")
    assert r["data"]["memory"]["disagreements"] and "follow MBTA's advice" in r["summary"]
