"""M13 A4: structured-claims answers. Each claim cites the tool steps it rests on and is checked on its own; a failed
claim is replaced by its cited step's own summary. Property tests (seeded): no claim with a lift number or a
number that is not in its cited steps passes; claims made from the steps' own summaries always pass."""
import random

from lastlift.agent import grounding

RESULTS = [
    {"tool": "platform_redundancy", "summary": "Revere Beach: 2 platforms; 1 loses step-free access now in the "
     "open-data model (Wonderland platform); lift(s) closed here now: 885",
     "data": {"platforms": [{"stop_id": "70058", "board": {"k": 0}, "exit": {"k": 0}}]},
     "entities": ["885", "884", "70058", "place-rbmnl"]},
    {"tool": "step_free_route", "summary": "1 step-free route from Revere Beach: ride to Wonderland and back, "
     "lifts 884, about 17.1 min", "data": {"routes": [{"minutes": 17.1, "lifts": ["884"]}]},
     "entities": ["884", "place-rbmnl", "place-wondl"]},
]


def test_a_good_claim_passes_and_a_fabricated_one_is_replaced():
    claims = [{"kind": "verdict", "text": "The Wonderland platform loses step-free access while lift 885 is out.",
               "cites": [1]},
              {"kind": "route", "text": "Lift 999 at Revere Beach takes about 25 minutes.", "cites": [2]}]
    text, report = grounding.assemble(claims, RESULTS)
    assert report[0]["ok"] and not report[1]["ok"]
    assert any("999" in p for p in report[1]["problems"]) and "999" not in text
    assert report[1]["replaced_by"].startswith("1 step-free route from Revere Beach")
    assert text.endswith("Check mbta.com/alerts/access.")


def test_rules_c1_and_c3():
    assert grounding.check_claim({"text": "Lift 885 is closed.", "cites": []}, RESULTS) == ["C1 cites no existing step"]
    assert grounding.check_claim({"text": "Lift 885 is closed.", "cites": [7]}, RESULTS) == ["C1 cites no existing step"]
    # loss wording cited only to a route step that shows no loss
    assert any(p.startswith("C3") for p in grounding.check_claim(
        {"text": "Revere Beach loses step-free access.", "cites": [2]}, RESULTS))


def test_property_off_ledger_numbers_never_pass():
    rng = random.Random(1017)
    ledger = {"885", "884", "70058", "17.1", "17", "2", "1"}
    for _ in range(300):
        n = str(rng.randint(100, 99999))
        if n in ledger:
            continue
        claim = {"text": rng.choice([f"Lift {n} is the last lift.", f"Platform {n} has no lift.",
                                     f"It takes {n} minutes.", f"{n} platforms are affected."]),
                 "cites": [rng.choice([1, 2])]}
        assert grounding.check_claim(claim, RESULTS), claim


def test_property_claims_from_step_summaries_always_pass():
    for i, r in enumerate(RESULTS, 1):
        for sentence in r["summary"].split("; "):
            assert grounding.check_claim({"text": sentence, "cites": [i]}, RESULTS) == [], sentence


def test_parse_claims_is_lenient_and_rejects_prose():
    good = 'Sure: {"claims": [{"kind": "verdict", "text": "Lift 885 is closed.", "cites": ["1"]}]} done'
    assert grounding.parse_claims(good) == [{"kind": "verdict", "text": "Lift 885 is closed.", "cites": [1]}]
    assert grounding.parse_claims("Lift 885 is closed.") is None
    assert grounding.parse_claims('{"claims": []}') is None


def test_agent_ships_verified_claims_and_replaces_a_fabricated_one(monkeypatch):
    import asyncio

    import pytest

    from lastlift import db
    from lastlift.agent import llm, loop
    if not db.ping():
        pytest.skip("FalkorDB not reachable")
    replies = iter([
        {"content": "", "tool_calls": [{"id": "c1", "type": "function",
                                        "function": {"name": "current_closures", "arguments": "{}"}}]},
        {"content": '{"claims": [{"kind": "verdict", "text": "Lift 885 is closed.", "cites": [1]}, '
                    '{"kind": "count", "text": "Lift 999 is closed too.", "cites": [1]}]}'},
    ])
    monkeypatch.setattr(llm, "chat", lambda *a, **k: next(replies))
    r = asyncio.run(loop.ask("Which lifts are closed right now?", mode="live"))
    g = next(e for e in r["events"] if e["type"] == "grounding")
    assert r["source"] == "llm" and "Lift 885 is closed." in r["answer"] and "999" not in r["answer"]
    assert [c["ok"] for c in g["claims"]] == [True, False] and g["claims"][1]["replaced_by"]
