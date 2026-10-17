"""Domain regressions on the committed snapshot (no graph server), and the eval's match rules.

G15-G19 are known stations where a wrong model would tell a rider a platform is reachable when it is
not (or the reverse). They pin the overrides in data/overrides.csv and the facility fix."""
import collections
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lastlift.routing import Topology  # noqa: E402

SNAP = sorted(p for p in (ROOT / "data" / "snapshots").iterdir() if (p / "MANIFEST.json").is_file())[-1]
NODES = [json.loads(l) for l in (SNAP / "nodes.jsonl").read_text(encoding="utf-8").splitlines()]
EDGES = [json.loads(l) for l in (SNAP / "edges.jsonl").read_text(encoding="utf-8").splitlines()]
TOPO = Topology.from_rows(NODES, EDGES)
ADJ = collections.defaultdict(list)
for e in EDGES:
    if e["type"] == "SF":
        ADJ[e["a"]].append((e["b"], e.get("facility_id") if e["kind"] == "lift" else None))
PLATFORMS = collections.defaultdict(list)
for n in NODES:
    if "Platform" in n["labels"] and "Node" in n["labels"]:
        PLATFORMS[n["station_id"]].append(n["uid"])


def reach(src, dst, closed):
    seen, todo, dst = set(src), list(src), set(dst)
    while todo:
        u = todo.pop()
        if u in dst:
            return True
        for v, f in ADJ[u]:
            if f not in closed and v not in seen:
                seen.add(v)
                todo.append(v)
    return False


def lost(station, facility):
    """Platform uids at `station` that lose boarding or exit when `facility` closes."""
    street = [f"street:{station}"]
    out = set()
    for p in PLATFORMS[station]:
        for s, t in ((street, [p]), ([p], street)):
            if reach(s, t, set()) and not reach(s, t, {facility}):
                out.add(p)
    return out


def test_g15_sullivan_840_centre_platform_loses_access_after_override():
    # Before the override the centre half shared a node with the side platform and looked reachable.
    assert "70031#centre" in lost("place-sull", "840")
    assert "70031" not in lost("place-sull", "840")


def test_g16_science_park_980_loses_copley_and_west_platform():
    assert lost("place-spmnl", "980") == {"70208"}


def test_g17_quincy_adams_736_has_an_in_station_alternative():
    # Pathways named 805 but tagged facility 736 in GTFS; the override retags them.
    assert lost("place-qamnl", "736") == set()


def test_g18_copley_976_reroutes_via_arlington_and_977():
    assert lost("place-coecl", "976") == {"70154"}
    cost, path = TOPO.shortest(["70154"], ["street:place-coecl"], ["976"])
    stations = {TOPO.nodes[e.b].get("station_id") for e in path}
    assert "place-armnl" in stations and "977" in [e.facility_id for e in path if e.kind == "lift"]


def test_g19_braintree_811_never_invents_a_shuttle():
    assert "70105" in lost("place-brntn", "811")
    cost, path = TOPO.shortest(["70105"], ["street:place-brntn"], ["811"])
    assert all(e.type in ("SF", "RIDE") for e in path)      # trains and step-free paths only


# --- the eval's match rules (scripts/eval.py) ----------------------------------------------------
import eval as ev  # noqa: E402


def gold(v, board="NOT_STATED", exit_="NOT_STATED"):
    return {"exp_verdict": v, "mbta_board_class": board, "mbta_exit_class": exit_}


def model(v, lost_board=(), lost_exit=()):
    return {"verdict": v, "lost": {"board": list(lost_board), "exit": list(lost_exit)}}


@pytest.mark.parametrize("g, m, want", [
    (gold("OUT_OF_SCOPE"), model("CANNOT_ASSESS"), "ABSTAIN_OK"),
    (gold("CANNOT_ASSESS"), model("NO_LOSS"), "GOLD_ABSTAINS"),
    (gold("NO_LOSS", "IN_STATION", "IN_STATION"), model("CANNOT_ASSESS"), "MODEL_ABSTAINS"),
    (gold("LOSS", "RIDE_AND_RETURN", "RIDE_AND_RETURN"), model("LOSS", ["p"], ["p"]), "AGREE"),
    (gold("LOSS", "RIDE_AND_RETURN", "IN_STATION"), model("LOSS", ["p"], ["p"]), "PARTIAL"),
    (gold("LOSS", "OTHER_STATION", "IN_STATION"), model("ENTRANCE_ONLY"), "PARTIAL"),      # State 803
    (gold("NO_LOSS", "IN_STATION", "NOT_STATED"), model("ENTRANCE_ONLY"), "PARTIAL"),      # Kendall 777
    (gold("LOSS", "RIDE_AND_RETURN", "RIDE_AND_RETURN"), model("NO_LOSS"), "DISAGREE"),
    (gold("ENTRANCE_ONLY"), model("ENTRANCE_ONLY"), "AGREE"),
])
def test_match_rules(g, m, want):
    assert ev.match(g, m) == want


def test_wilson_interval():
    assert ev.wilson(6, 8) == (0.409, 0.929)
    assert ev.wilson(0, 0) == (None, None)


def test_committed_eval_is_scored_against_the_author_key():
    import csv
    rows = list(csv.DictReader((ROOT / "validation" / "eval_live.csv").open(encoding="utf-8")))
    key = {r["gold_id"]: r for r in csv.DictReader((ROOT / "validation" / "gold_live_author.csv").open(encoding="utf-8-sig"))}
    assert len(rows) == len(key) == 14
    for r in rows:
        assert r["exp_verdict"] == key[r["gold_id"]]["exp_verdict"]
        assert r["labelled_by"].startswith("author")
        assert r["match"] == ev.match(r, {"verdict": r["model_verdict"],
                                          "lost": {"board": [x for x in r["model_lost_board"].split(";") if x],
                                                   "exit": [x for x in r["model_lost_exit"].split(";") if x]}})
    claims = json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))
    assert claims["live_agree"] == sum(r["match"] == "AGREE" for r in rows)
    assert claims["live_false_accessible"] == len(claims["live_false_accessible_cases"])
