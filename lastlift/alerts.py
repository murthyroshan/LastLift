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
ELEVATOR_TYPES = {"ELEVATOR", "PORTABLE_BOARDING_LIFT", "ELEVATED_SUBPLATFORM"}


@lru_cache(maxsize=1)
def latest_versions() -> dict:
    """alert id -> latest captured version (from the committed harvest)."""
    latest = {}
    if not ALERTS_FILE.is_file():
        return latest
    for line in ALERTS_FILE.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        aid = rec["alert"]["id"]
        if aid not in latest or rec["captured_at"] > latest[aid]["captured_at"]:
            latest[aid] = rec
    return latest


def lift_alerts(alert_ids=None) -> list[dict]:
    """Elevator-related alerts with their facility ids, newest version each."""
    out = []
    for aid, rec in sorted(latest_versions().items()):
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
        out.append({"alert_id": aid, "effect": attrs.get("effect"), "facility_ids": fids, "stations": stations,
                    "header": attrs.get("header"), "updated_at": attrs.get("updated_at"),
                    "captured_at": rec["captured_at"]})
    return out


def demo_alert_ids() -> list[str] | None:
    """The frozen alert set behind the judged 'demo' scope (None if not frozen yet)."""
    if DEMO_FILE.is_file():
        return json.loads(DEMO_FILE.read_text(encoding="utf-8"))["alert_ids"]
    return None


def closures_for(scope: str) -> list[dict]:
    if scope == "demo":
        ids = demo_alert_ids()
        return lift_alerts(set(ids)) if ids is not None else []
    if scope == "live":
        return lift_alerts()
    return []
