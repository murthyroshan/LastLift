"""The pre-registered evaluation inputs are well formed (they are committed before any run)."""
import json
from collections import Counter
from pathlib import Path

import yaml

from lastlift import tools

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = {"closure_impact": 6, "redundancy": 4, "what_if": 4, "reroute": 4, "priority": 3,
              "must_abstain": 3, "adversarial": 3, "multi_intent": 3}


def test_gold_questions_match_the_protocol():
    data = yaml.safe_load((ROOT / "eval" / "gold_questions.yaml").read_text(encoding="utf-8"))
    qs = data["questions"]
    assert len(qs) == 30 and len({q["id"] for q in qs}) == 30
    assert Counter(q["category"] for q in qs) == CATEGORIES
    for q in qs:
        for t in q.get("required_tools", []) + q.get("forbidden_tools", []):
            assert t in tools.REGISTRY, (q["id"], t)
        assert q.get("must_abstain", False) == (q["category"] == "must_abstain")


def test_every_sample_has_a_fixed_seed():
    s = json.loads((ROOT / "eval" / "sampling.json").read_text(encoding="utf-8"))
    assert all(isinstance(v["seed"], int) for k, v in s.items() if k != "note")


def test_protocols_exist():
    for p in ("validation/VALIDATION_PROTOCOL.md", "eval/protocol.md", "eval/llm_baseline.md", "eval/sensitivity.md"):
        assert (ROOT / p).stat().st_size > 500, p
