"""M11 Lift Ledger: totals reproduce from committed files; interval reconstruction; service hours and Boston time;
20 random replay moments re-checked by FalkorDB's certified max-flow; backtest and claims agree; no MBTA text
committed for the historical gold."""
import csv
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "ingest"))

import history_replay as hr  # noqa: E402
from history import eastern_offset  # noqa: E402

from lastlift import db, redundancy, seed, state, tools  # noqa: E402
from lastlift.queries import Q_CLOSE_LIFTS, Q_COMPLEX_PLATFORMS, Q_COMPLEX_STREETS, Q_REOPEN_LIFTS  # noqa: E402

CLAIMS = json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))
NET = json.loads((seed.latest_snapshot() / "network.json").read_text(encoding="utf-8"))
REPLAY = json.loads((hr.HIST / "replay.json").read_text(encoding="utf-8"))
needs_db = pytest.mark.skipif(not db.ping(), reason="FalkorDB not reachable")
UTC = timezone.utc


@pytest.fixture(scope="module")
def ledger():
    ws = hr.merged_windows()
    eps = hr.episodes(ws)
    sw = json.loads((hr.HIST / "service_windows.json").read_text(encoding="utf-8"))
    return ws, eps, hr.replay(eps, NET["platform"], set(NET["lifts"]), sw, hr.LEDGER_FROM), sw


def test_published_totals_reproduce_from_committed_files(ledger):
    _, eps, (per_dir, _per_lift, _daily, conc), _ = ledger
    total = sum(x["svc_h"] for x in per_dir.values())
    assert len(per_dir) == CLAIMS["hist_dirs_lost"]
    assert round(total) == CLAIMS["hist_lost_service_h"]
    assert round(sum(x["single_svc_h"] for x in per_dir.values()) / total, 4) == CLAIMS["hist_single_share"]
    assert sum(conc.values()) == CLAIMS["hist_concurrent_losses"]
    assert sum(len(v) for v in eps.values()) == CLAIMS["hist_episodes"]


@pytest.mark.parametrize("fid", ["885", "876", "854", "811", "922"])
def test_interval_reconstruction(ledger, fid):
    """Episodes are ordered, separated by more than the merge gap, and each covers every window it was built from."""
    ws, eps, _, _ = ledger
    es = eps[fid]
    assert es and all(s < e for s, e, *_ in es)
    for (s1, e1, *_), (s2, *_r) in zip(es, es[1:]):
        assert s2 - e1 > timedelta(minutes=hr.GAP_MIN)
    for w in (w for w in ws if w["facility_id"] == fid):
        end = w["end_recorded"] or w["end_low"]
        if end <= w["start"]:
            continue
        home = [x for x in es if x[0] <= w["start"] and end <= x[1]]
        assert len(home) == 1 and w["alert_id"] in home[0][3], (fid, w["alert_id"])
        if w["end_recorded"] is None:
            assert home[0][2] is True                 # imputed ends are flagged


def test_boston_time_and_service_hours():
    assert eastern_offset(datetime(2026, 3, 8, 6, 59, tzinfo=UTC)) == timedelta(hours=-5)
    assert eastern_offset(datetime(2026, 3, 8, 7, 0, tzinfo=UTC)) == timedelta(hours=-4)
    assert eastern_offset(datetime(2026, 11, 1, 5, 59, tzinfo=UTC)) == timedelta(hours=-4)
    assert eastern_offset(datetime(2026, 11, 1, 6, 0, tzinfo=UTC)) == timedelta(hours=-5)
    win = {"weekday": [5 * 3600, 25 * 3600], "saturday": [6 * 3600, 25 * 3600], "sunday": [7 * 3600, 24 * 3600]}
    # Wed 14 Oct 2026, local 00:00 -> 24:00 (EDT, UTC-4): service 01:00 (Tue's day runs to 01:00) and 05:00 -> 24:00
    t0 = datetime(2026, 10, 14, 4, 0, tzinfo=UTC)
    assert abs(hr.service_hours(win, t0, t0 + timedelta(hours=24)) - 20.0) < 1e-9
    assert hr.service_hours({}, t0, t0 + timedelta(hours=5)) == 0.0


def test_backtest_matches_claims_and_states_its_failure():
    bt = json.loads((hr.HIST / "backtest.json").read_text(encoding="utf-8"))
    assert bt["h6"]["hours_x_impact_2024"]["spearman"] == CLAIMS["hist_bt_spearman"]
    assert bt["h5"]["skill"] == CLAIMS["hist_bt_brier_skill"]
    report = (ROOT / "validation" / "HISTORY.md").read_text(encoding="utf-8")
    met = bt["h5"]["calibrated"] and bt["h5"]["skill"] >= 0.3
    assert ("**met**" in report) == met and ("**not met**" in report) == (not met)
    from backtest import spearman
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0 and spearman([1, 2, 3], [3, 2, 1]) == -1.0


def test_historical_gold_commits_no_mbta_text():
    rows = list(csv.DictReader((ROOT / "validation" / "history_gold_ids.csv").open(encoding="utf-8")))
    assert len(rows) == 20 and set(rows[0]) == {"gold_id", "alert_id", "facility_ids", "start", "description_sha256"}


@needs_db
def test_twenty_replay_moments_equal_falkordb_maxflow(ledger):
    """At 20 random moments of the replay (seeded), close the lifts that were closed then on a copy of the graph:
    a platform-direction has FalkorDB max-flow 0 exactly when the replay says it lost step-free access."""
    _, eps, _, _ = ledger
    modelled = set(NET["lifts"])
    starts = sorted(s for f, es in eps.items() if f in modelled for s, *_ in es if s >= hr.LEDGER_FROM)
    rng = random.Random(1021)
    moments = [t + timedelta(minutes=1) for t in rng.sample(starts, 20)]
    base = state.graph_name("base")
    name = state.graph_name(f"wi_test_hist_{os.getpid()}")
    if state.exists(name):
        db.client().select_graph(name).delete()
    db.client().connection.execute_command("GRAPH.COPY", base, name)
    g = db.client().select_graph(name)
    checked = 0
    try:
        for t in moments:
            closed = {f for f, es in eps.items() if f in modelled and any(s <= t < e for s, e, *_ in es)}
            g.query(Q_REOPEN_LIFTS, {"fids": []})
            g.query(Q_CLOSE_LIFTS, {"fids": sorted(closed)})
            cxs = {p["cx"] for p in NET["platform"].values()
                   if any(f in closed for d in ("board", "exit") for f in (p[d].get("relevant") or []))}
            for cx in sorted(cxs):
                edges, lf = redundancy.complex_edges(g, cx)
                streets = g.ro_query(Q_COMPLEX_STREETS, {"cx": cx}).result_set[0][0]
                uids = {r[0]: r[1] for r in g.ro_query(Q_COMPLEX_PLATFORMS, {"cx": cx}).result_set}
                for stop, p in NET["platform"].items():
                    if p["cx"] != cx:
                        continue
                    for d in ("board", "exit"):
                        sets = [set(x) for x in p[d].get("minimal") or []]
                        if not sets:
                            continue
                        lost = any(s <= closed for s in sets)
                        src, dst = (streets, uids[stop]) if d == "board" else (uids[stop], streets)
                        k = redundancy.direction(g, edges, lf, src, dst).k
                        assert (k == 0) == lost, (t, stop, d, sorted(closed))
                        checked += 1
    finally:
        if state.exists(name):
            db.client().select_graph(name).delete()
    assert checked >= 20


@needs_db
def test_lift_history_tool_reports_the_archive():
    tools.prepare_scope("demo")
    r = tools.lift_history("811")
    a = r["data"]["archive"]
    assert a and a["closures"] > 0 and "not a forecast" in r["summary"]
    assert a["step_free_service_hours_lost_alone"] == REPLAY["lifts"]["811"]["single_svc_h"]
