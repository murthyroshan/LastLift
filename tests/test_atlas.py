"""M15 MS5 Atlas and MS2 city sweep: the generic rules reproduce the MBTA count, FalkorDB agrees with the exact
solver on every checked platform-direction, the public file names only licence-checked agencies, and the line
orders reference real stations."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

ATLAS = ROOT / "data" / "atlas.json"
PUBLIC = ROOT / "web" / "public" / "m" / "atlas.json"
CLAIMS = json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))


@pytest.mark.skipif(not ATLAS.is_file(), reason="atlas sweep not run")
def test_mbta_under_generic_rules_is_the_oracle():
    rows = {r["id"]: r for r in json.loads(ATLAS.read_text(encoding="utf-8"))["agencies"]}
    assert rows["mdb-437"]["single_lift"] == CLAIMS["platforms_single_lift"]


@pytest.mark.skipif(not ATLAS.is_file(), reason="atlas sweep not run")
def test_falkordb_agrees_everywhere_and_claims_match():
    rows = json.loads(ATLAS.read_text(encoding="utf-8"))["agencies"]
    checked = sum(r["falkordb"].get("checked", 0) for r in rows)
    assert checked > 0 and checked == sum(r["falkordb"].get("equal", 0) for r in rows)
    assert CLAIMS["atlas_falkordb_checked"] == checked == CLAIMS["atlas_falkordb_equal"]
    assert CLAIMS["atlas_feeds"] == len(rows)


@pytest.mark.skipif(not PUBLIC.is_file(), reason="atlas not published")
def test_public_atlas_names_only_licence_checked_agencies():
    gate = json.loads((ROOT / "data" / "atlas_licences.json").read_text(encoding="utf-8"))
    pub = json.loads(PUBLIC.read_text(encoding="utf-8"))
    assert {a["id"] for a in pub["agencies"]} == {k for k, v in gate.items() if v == "include"}
    text = PUBLIC.read_text(encoding="utf-8")
    full = json.loads(ATLAS.read_text(encoding="utf-8"))["agencies"]
    for r in full:
        if gate.get(r["id"]) != "include":
            assert r["provider"] not in text, f"{r['id']} named before its licence was checked"


def test_merge_keeps_one_edge_per_pair_and_sums_capacity():
    from atlas_sweep import BIG, merge
    out = merge([("a", "x", "y", 1), ("b", "x", "y", 2), ("c", "y", "x", BIG), ("d", "y", "x", BIG)])
    assert sorted((u, v, c) for _, u, v, c in out) == [("x", "y", 3), ("y", "x", BIG)]


def test_line_orders_reference_mapped_stations():
    lines = json.loads((ROOT / "web" / "public" / "m" / "lines.json").read_text(encoding="utf-8"))["lines"]
    stations = {s["id"] for s in json.loads((ROOT / "web" / "public" / "m" / "map.json").read_text(encoding="utf-8"))["stations"]}
    assert len(lines) >= 6
    for ln in lines:
        assert len(ln["stations"]) >= 3 and len(set(ln["stations"])) == len(ln["stations"])
        missing = [s for s in ln["stations"] if s not in stations]
        assert len(missing) <= 1, f"{ln['name']}: {missing}"
