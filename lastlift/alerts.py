"""MBTA accessibility alerts -> lift closures.

Alerts are selected by facility type (elevator-like facilities), not by effect: some elevator
outages are published as ACCESS_ISSUE rather than ELEVATOR_CLOSURE. Each closure is then scoped:
  modelled       - the lift is in the step-free graph, so its impact can be computed
  cannot_assess  - the lift exists but its station has no pathway data (e.g. many commuter-rail stops)
"""
import json
from functools import lru_cache

from .config import REPO_ROOT

ALERTS_FILE = REPO_ROOT / "data" / "alerts" / "accessibility_alert_versions.jsonl"
DEMO_FILE = REPO_ROOT / "data" / "alerts" / "demo_closures.json"
ACTIVITY_FILE = REPO_ROOT / "data" / "alerts" / "alert_activity.json"
ELEVATOR_TYPES = {"ELEVATOR", "PORTABLE_BOARDING_LIFT", "ELEVATED_SUBPLATFORM"}


@lru_cache(maxsize=4)
def latest_versions(cutoff: str | None = None) -> dict:
    """alert id -> latest version captured at or before `cutoff` (ISO time; None = no cutoff)."""
    latest = {}
    if not ALERTS_FILE.is_file():
        return latest
    for line in ALERTS_FILE.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if cutoff and rec["captured_at"] > cutoff:
            continue
        aid = rec["alert"]["id"]
        if aid not in latest or rec["captured_at"] > latest[aid]["captured_at"]:
            latest[aid] = rec
    return latest


@lru_cache(maxsize=1)
def activity() -> dict:
    """When the collector saw each accessibility alert active (from data/alerts/alert_activity.json)."""
    if not ACTIVITY_FILE.is_file():
        return {"first_poll": None, "last_poll": None, "polls": 0, "alerts": {}}
    return json.loads(ACTIVITY_FILE.read_text(encoding="utf-8"))


def lift_alerts(alert_ids=None, cutoff: str | None = None) -> list[dict]:
    """Elevator-related alerts with their facility ids, newest version (at or before `cutoff`) each."""
    out = []
    for aid, rec in sorted(latest_versions(cutoff).items()):
        if alert_ids is not None and aid not in alert_ids:
            continue
        attrs = rec["alert"]["attributes"]
        types = rec.get("facility_types", {})
        fids = sorted({ie["facility"] for ie in attrs.get("informed_entity", [])
                       if ie.get("facility") and types.get(ie["facility"]) in ELEVATOR_TYPES})
        if not fids and attrs.get("effect") == "ELEVATOR_CLOSURE":
            fids = sorted({ie["facility"] for ie in attrs.get("informed_entity", []) if ie.get("facility")})
        if not fids:
            continue
        stations = sorted({ie["stop"] for ie in attrs.get("informed_entity", []) if str(ie.get("stop", "")).startswith("place-")})
        periods = attrs.get("active_period") or []
        out.append({"alert_id": aid, "effect": attrs.get("effect"), "facility_ids": fids, "stations": stations,
                    "header": attrs.get("header"), "updated_at": attrs.get("updated_at"),
                    "started": periods[0].get("start") if periods else None, "captured_at": rec["captured_at"]})
    return out


def demo_freeze() -> dict | None:
    """The frozen alert set behind the judged 'demo' scope: {alert_ids, frozen_at} (None if not frozen)."""
    if DEMO_FILE.is_file():
        return json.loads(DEMO_FILE.read_text(encoding="utf-8"))
    return None


def demo_alert_ids() -> list[str] | None:
    f = demo_freeze()
    return f["alert_ids"] if f else None


def closures_for(scope: str) -> list[dict]:
    if scope == "demo":
        f = demo_freeze()  # versions captured after the freeze never change the demo
        return lift_alerts(set(f["alert_ids"]), cutoff=f["frozen_at"]) if f else []
    if scope == "live":
        return lift_alerts()
    return []
