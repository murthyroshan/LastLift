"""Live feed (LIVE_FEED=on): poll the MBTA V3 alerts API and keep the live scope graph in step with it.

Each successful poll turns the alerts into lift closures with the same facility-type rule as the harvest
(alerts.closure), syncs the live graph to the modelled closed lifts (only changed complexes are recomputed) and
bumps `state_version` when the closed set changes. The status is stale when the last good poll is more than
STALE_S old; until a poll succeeds the live scope uses the committed harvest. Writes go only to the live graph.
"""
import asyncio
import hashlib
import logging
import threading
from datetime import datetime, timezone

import httpx

from . import alerts, state
from .config import settings

log = logging.getLogger("lastlift.live")
URL = "https://api-v3.mbta.com/alerts?include=facilities"
STALE_S = 300
TIMEOUT_S = 20

_lock = threading.Lock()
_status = {"polls": 0, "failures": 0, "last_ok_at": None, "last_error": None, "state_version": 0,
           "closed_hash": None, "alerts": None, "closed": [], "changed": []}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def fetch() -> dict:
    headers = {"Accept": "application/vnd.api+json", "User-Agent": "lastlift"}
    if settings.mbta_api_key:
        headers["x-api-key"] = settings.mbta_api_key
    r = httpx.get(URL, headers=headers, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()


def closures_from(body: dict, captured_at: str) -> list[dict]:
    types = {f["id"]: (f.get("attributes") or {}).get("type") for f in body.get("included", [])
             if f.get("type") == "facility"}
    out = [alerts.closure(a, types, captured_at) for a in body.get("data", [])]
    return sorted((c for c in out if c), key=lambda c: c["alert_id"])


def poll_once(fetcher=fetch) -> dict:
    """One poll: fetch, sync the live graph, update the status. Never raises for a feed failure."""
    from .tools import modelled_closed_facilities     # tools imports alerts and state; keep the import local
    now = _now().isoformat(timespec="seconds")
    try:
        body = fetcher()
    except (httpx.HTTPError, ValueError) as exc:
        code = getattr(getattr(exc, "response", None), "status_code", None)
        with _lock:
            _status["failures"] += 1
            _status["last_error"] = f"{now} {type(exc).__name__}" + (f" HTTP {code}" if code else "")
        log.warning("live poll failed: %s", _status["last_error"])
        return status()
    closures = closures_from(body, now)
    fids = modelled_closed_facilities(closures)
    res = state.ensure_scope("live", fids)
    alerts.set_live(closures, now)
    digest = hashlib.sha1(",".join(fids).encode()).hexdigest()[:12]
    with _lock:
        _status["polls"] += 1
        _status["last_ok_at"] = now
        if digest != _status["closed_hash"]:
            _status["state_version"] += 1
            _status["closed_hash"] = digest
        _status.update(alerts=len(closures), closed=fids, changed=res.get("changed", []))
    return status()


def status() -> dict:
    with _lock:
        s = dict(_status)
    age = None
    if s["last_ok_at"]:
        age = round((_now() - datetime.fromisoformat(s["last_ok_at"])).total_seconds())
    return {"feed": settings.live_feed, "source": "mbta_api" if s["last_ok_at"] else "harvest",
            "poll_interval_s": settings.live_poll_s, "age_s": age, "stale": age is None or age > STALE_S, **s}


async def run_forever(interval_s: int):
    """Background poll loop started by the API when LIVE_FEED=on."""
    while True:
        try:
            await asyncio.to_thread(poll_once)
            from .tools import warm             # a no-op unless the closures changed: then the new analyses are ready first
            await asyncio.to_thread(warm, ("live",))
        except Exception as exc:            # graph server down: keep the loop alive, report it in the status
            with _lock:
                _status["failures"] += 1
                _status["last_error"] = f"{_now().isoformat(timespec='seconds')} {type(exc).__name__}"
            log.warning("live sync failed: %s", type(exc).__name__)
        await asyncio.sleep(max(15, interval_s))
