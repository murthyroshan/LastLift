"""M13 A8: replays are hash-chained; one edited byte breaks the chain at that event."""
import copy
import json

import pytest

from lastlift.agent import replay

IDS = sorted(p.stem for p in replay.REPLAY_DIR.glob("*.json") if p.stem != "index")


@pytest.mark.parametrize("rid", IDS)
def test_every_replay_is_sealed_and_intact(rid):
    assert replay.chain_problems(replay.load(rid)) == []


def test_one_edited_byte_breaks_the_chain_at_that_event():
    rec = replay.load(IDS[0])
    i = next(n for n, e in enumerate(rec["events"]) if e["type"] == "tool_result")
    bad = copy.deepcopy(rec)
    s = bad["events"][i]["summary"]
    bad["events"][i]["summary"] = s[:-1] + ("x" if s[-1] != "x" else "y")
    assert replay.chain_problems(bad) == [f"{rid_of(rec)}: hash chain broken at event {i + 1}"]
    tampered_head = copy.deepcopy(rec)
    tampered_head["head"] = "0" * 64
    assert replay.chain_problems(tampered_head)


def test_canonical_json_matches_the_browser_form():
    assert replay.jscanon({"b": 1.0, "a": [2.5, {"z": None, "y": "é"}]}) == '{"a":[2.5,{"y":"é","z":null}],"b":1}'


def rid_of(rec):
    return rec["id"]
