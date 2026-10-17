"""The website states no number of its own, serves the same claims as the repo, and its mirror is complete."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
STRING = re.compile(r"\"([^\"\\]*(?:\\.[^\"\\]*)*)\"|`([^`]*)`")
JSX_TEXT = re.compile(r">([^<>{}();=?&|]*\d[^<>{}();=?&|]*)</")   # text right before a closing tag


def test_ui_strings_hold_no_numbers():
    """Every number on screen comes from claims.json, the mirror or the API, never from a typed string."""
    src = (WEB / "src" / "strings.en.ts").read_text(encoding="utf-8")
    for m in STRING.finditer(src):
        text = re.sub(r"\$\{[^}]*\}", "", m.group(1) or m.group(2) or "")    # placeholders are data
        assert not re.search(r"\d", text), f"number typed into a UI string: {text!r}"


def test_jsx_text_holds_no_numbers():
    for path in (WEB / "src").rglob("*.tsx"):
        for m in JSX_TEXT.finditer(path.read_text(encoding="utf-8")):
            assert not m.group(1).strip(), f"{path.name}: number typed into JSX text: {m.group(1)!r}"


def test_web_claims_are_the_repo_claims():
    assert (WEB / "public" / "claims.json").read_bytes() == (ROOT / "claims.json").read_bytes()


def test_mirror_covers_every_listed_station_and_the_story():
    m = WEB / "public" / "m"
    stations = json.loads((m / "stations.json").read_text(encoding="utf-8"))
    assert len(stations) > 0
    for s in stations:
        bundle = json.loads((m / "station" / f"{s['id']}.json").read_text(encoding="utf-8"))
        assert {"board", "exit"} <= set(bundle["graph"]) and bundle["redundancy"]["ok"]
    state = json.loads((m / "state.json").read_text(encoding="utf-8"))
    for lp in state["closures"]["data"]["platforms_lost"]:
        assert (m / "reroute" / f"{lp['stop_id']}.json").is_file()
    for r in state["priority"]["data"]["ranked"]:
        if r["tier"] <= 2:
            assert (m / "ticket" / f"{r['facility_id']}.json").is_file()
    assert (m / "whatif" / "813.json").is_file() and (m / "queries.json").is_file()
