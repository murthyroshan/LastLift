"""Incident memory: every lift closure the collector has seen, written into the graph.

    (:Lift)-[:CLOSED_IN]->(:Incident {alert_id, effect, header, started, first_seen, last_seen,
                                      ongoing, ended_by, versions})

One Incident per MBTA alert. `started` is MBTA's active_period start; `first_seen` / `last_seen` come
from the collector's polls; `ongoing` is false once the alert is missing from the latest poll.
`ended_by` is the first poll that no longer listed it: the closure ended (or the alert was
withdrawn) between `last_seen` and `ended_by`. MBTA's alerts are the source; nothing here is
inferred about actual lift status.

The demo scope is frozen: it only knows alerts captured up to its `frozen_at`, as of that moment.
"""
import json

from . import alerts, db, state
from .queries import Q_CLEAR_INCIDENTS, Q_WRITE_INCIDENTS


def build(cutoff: str | None = None) -> list[dict]:
    act = alerts.activity()
    last_poll = act.get("last_poll")
    rows = []
    for a in alerts.lift_alerts(cutoff=cutoff):
        seen = act["alerts"].get(a["alert_id"], {})
        first_seen = seen.get("first_active") or a["captured_at"]
        last_seen = seen.get("last_active") or a["captured_at"]
        if cutoff:                       # as of the freeze: everything captured then was active then
            ongoing, ended_by = True, None
            last_seen = min(last_seen, cutoff)
        else:
            ongoing = bool(last_poll) and last_seen >= last_poll
            ended_by = None if ongoing else seen.get("first_absent")
        versions = _versions(a["alert_id"], cutoff)
        rows.append({"alert_id": a["alert_id"], "fids": a["facility_ids"], "p": {
            "alert_id": a["alert_id"], "effect": a["effect"], "header": a["header"], "started": a["started"],
            "first_seen": first_seen, "last_seen": last_seen, "ongoing": ongoing, "ended_by": ended_by,
            "versions": versions, "stations": a["stations"]}})
    return rows


def _versions(alert_id, cutoff):
    """How many distinct versions of the alert were captured (up to `cutoff`)."""
    if not alerts.ALERTS_FILE.is_file():
        return 0
    recs = (json.loads(line) for line in alerts.ALERTS_FILE.read_text(encoding="utf-8").splitlines())
    return sum(1 for r in recs if r["alert"]["id"] == alert_id and (not cutoff or r["captured_at"] <= cutoff))


def sync(scope: str) -> int:
    """Replace the scope graph's incidents with the current memory. Returns the number written."""
    freeze = alerts.demo_freeze() if scope == "demo" else None
    rows = build(freeze["frozen_at"] if freeze else None)
    g = db.client().select_graph(state.graph_name(scope))
    g.query(Q_CLEAR_INCIDENTS)
    if rows:
        g.query(Q_WRITE_INCIDENTS, {"rows": rows})
    return len(rows)
