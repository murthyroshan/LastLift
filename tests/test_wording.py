"""Disclaimers and wording rules (no graph server)."""
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from lastlift import wording
from lastlift.main import app

ROOT = Path(__file__).resolve().parents[1]


def test_copy_lint_passes_on_the_repo():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "copy_lint.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_lint_catches_banned_phrases():
    for text in ("Riders are stranded at Chinatown", "This route is safe", "The station is accessible",
                 "MBTA says the lift is out", "LastLift predicts failures", "100% accurate", "4,000 disabled people"):
        assert wording.violations(text), text
    for text in ("loses step-free access in the open-data model", "no accessible entrance in data",
                 "safety metric", "cannot assess"):
        assert not wording.violations(text), text


def test_disclaimers_are_served_exactly():
    body = TestClient(app).get("/v1/disclaimers").json()
    assert body == wording.DISCLAIMERS
    assert "Not affiliated with or endorsed by the MBTA or MassDOT" in body["footer"]
    assert "617-222-2828" in body["footer"]


def test_feedback_channel_and_ethics_exist():
    template = (ROOT / ".github" / "ISSUE_TEMPLATE" / "accessibility-problem.yml").read_text(encoding="utf-8")
    assert "Report an accessibility problem with LastLift" in template
    assert "required: true" not in template            # every field optional
    ethics = (ROOT / "docs" / "ETHICS.md").read_text(encoding="utf-8")
    assert "not yet been reviewed by disabled riders" in ethics
