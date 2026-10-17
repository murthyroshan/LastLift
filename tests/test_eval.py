"""M12: the evaluation harness (deterministic scoring; the router run reproduces byte for byte), the baselines,
the endpoint, and the validation-study guards."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import baselines  # noqa: E402
import run as harness  # noqa: E402

from lastlift import db  # noqa: E402
from lastlift.main import app  # noqa: E402

needs_db = pytest.mark.skipif(not db.ping(), reason="FalkorDB not reachable")


def test_scoring_rules():
    q = {"id": "T", "category": "closure_impact", "required_tools": ["platform_redundancy"],
         "gold_ids": ["885"], "gold_verdicts": [{"platform": "70058", "dir": "board", "verdict": "lost"}],
         "forbidden_claims": ["safe"]}
    good = harness.score(q, "The Wonderland platform loses step-free access while lift 885 is closed.", [],
                         ["platform_redundancy"], "full")
    assert good["tools_ok"] and good["ids_ok"] and good["verdicts"] == [True] and good["false_accessible"] == 0
    bad = harness.score(q, "Revere Beach is safe and step-free.", [], ["current_closures"], "full")
    assert not bad["tools_ok"] and not bad["ids_ok"] and bad["false_accessible"] == 1 and bad["forbidden"] == ["safe"]
    # a count such as "6 cannot assess" in a summary is not an abstention
    assert not harness.ABSTAIN.search("14 lift alerts (8 modelled, 6 cannot assess)")
    assert harness.ABSTAIN.search("Cannot assess: lift 782 is not in the step-free model")
    assert harness.ids_found(["813"], "", [{"entities": ["813"], "summary": ""}])
    assert not harness.ids_found(["813"], "lift 8130", [])


@needs_db
def test_router_run_reproduces_byte_for_byte(tmp_path):
    committed = (ROOT / "eval" / "results" / "router.json").read_bytes()
    subprocess.run([sys.executable, str(ROOT / "eval" / "run.py"), "--system", "router"], check=True,
                   cwd=ROOT, capture_output=True, timeout=900)
    assert (ROOT / "eval" / "results" / "router.json").read_bytes() == committed


def test_count_and_bfs_baselines_are_reproducible():
    rows, net, lifts_at = baselines.certified()
    stored = json.loads((ROOT / "eval" / "results" / "baselines.json").read_text(encoding="utf-8"))
    assert baselines.b_count(rows, lifts_at) == stored["b_count"]
    assert baselines.b_bfs(net) == stored["b_bfs"]
    assert stored["b_count"]["rule_wrong"] == stored["b_count"]["misses_single"] + stored["b_count"]["says_single_but_not"]


def test_llm_baseline_keeps_every_prompt_and_answer():
    stored = json.loads((ROOT / "eval" / "results" / "baselines.json").read_text(encoding="utf-8"))["b_llm"]
    cached = list((ROOT / "eval" / "results" / "llm_baseline").glob("*.json"))
    assert stored["n"] == 30 and len(cached) == 30
    for p in cached:
        rec = json.loads(p.read_text(encoding="utf-8"))
        assert rec["prompt"] and rec["answer"] and "extracted" in rec and rec["model"] == stored["model"]


def test_eval_endpoint_serves_the_latest_results():
    with TestClient(app) as c:
        r = c.get("/v1/eval/latest")
        assert r.status_code == 200 and "router" in r.json()["systems"] and "baselines" in r.json()


def test_validation_study_scores_only_after_author_labels():
    if (ROOT / "validation" / "gold_static.csv").is_file():
        pytest.skip("author labels exist")
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "validation_study.py"), "--score"], cwd=ROOT,
                         capture_output=True, text=True)
    assert out.returncode == 1 and "no author labels yet" in out.stdout
