"""Guarantees of the committed snapshot: consistent with its manifest, flow-network invariants hold."""
import collections
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SNAP = sorted(p for p in (ROOT / "data" / "snapshots").iterdir() if (p / "MANIFEST.json").is_file())[-1]
MANIFEST = json.loads((SNAP / "MANIFEST.json").read_text(encoding="utf-8"))
NODES = [json.loads(l) for l in (SNAP / "nodes.jsonl").read_text(encoding="utf-8").splitlines()]
EDGES = [json.loads(l) for l in (SNAP / "edges.jsonl").read_text(encoding="utf-8").splitlines()]
BIG = MANIFEST["big"]


def test_file_hashes_match_manifest():
    for name, digest in MANIFEST["files"].items():
        assert hashlib.sha256((SNAP / name).read_bytes()).hexdigest() == digest


def test_counts_match_manifest():
    assert len(NODES) == MANIFEST["counts"]["nodes"]
    assert len(EDGES) == MANIFEST["counts"]["edges"]
    assert dict(collections.Counter(e["type"] for e in EDGES)) == MANIFEST["counts"]["edges_by_type"]


def test_no_parallel_flow_edges():
    pairs = collections.Counter((e["a"], e["b"]) for e in EDGES if e["type"] == "SF")
    assert max(pairs.values()) == 1


def test_capacities():
    for e in EDGES:
        if e["type"] == "SF":
            assert e["cap"] == (1 if e["kind"] == "lift" else BIG), e["eid"]


def test_every_lift_unit_has_one_core_edge():
    units = {n["uid"] for n in NODES if "Lift" in n["labels"] and "Node" in n["labels"]}
    cores = {e["a"] for e in EDGES if e["type"] == "SF" and e["kind"] == "lift"}
    assert units == cores and len(units) == 202


def test_overrides_applied():
    applied = MANIFEST["overrides_applied"]
    for key in ("split_platform:70031", "split_platform:70033", "facility_fix:qamnl-060",
                "facility_fix:qamnl-061", "entrance_accessible:door-coecl-bpl"):
        assert applied.get(key, 0) > 0, key
    uids = {n["uid"] for n in NODES}
    assert {"70031#centre", "70033#centre"} <= uids


def test_split_halves_are_not_walk_linked():
    """Crossing between the two halves of a split stop needs a train, so no SF edge may join them."""
    sf = {(e["a"], e["b"]) for e in EDGES if e["type"] == "SF"}
    for stop in ("70031", "70033"):
        assert (stop, f"{stop}#centre") not in sf and (f"{stop}#centre", stop) not in sf


def test_no_tool_internal_text_loaded():
    """MBTA's internal-use alternative-service text must never enter the served graph."""
    text = (SNAP / "nodes.jsonl").read_text(encoding="utf-8")
    assert "alternate-service-text" not in text and "cross through the train" not in text.lower()


@pytest.mark.skipif(not (ROOT / "data" / "raw" / "MBTA_GTFS.zip").is_file(), reason="raw GTFS not present")
def test_build_is_deterministic(tmp_path):
    out = subprocess.run([sys.executable, "-I", str(ROOT / "ingest" / "build_snapshot.py"),
                          "--gtfs", str(ROOT / "data" / "raw" / "MBTA_GTFS.zip"),
                          "--overrides", str(ROOT / "data" / "overrides.csv"),
                          "--date", SNAP.name, "--out", str(tmp_path)], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    rebuilt = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))
    assert rebuilt["seed_sha256"] == MANIFEST["seed_sha256"]
