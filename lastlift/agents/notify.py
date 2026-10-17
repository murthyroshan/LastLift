"""Rider notices through ntfy ("Follow a station"): one notice when a station loses or regains step-free access in
the open-data model, none when nothing changed. LastLift stores nothing about subscribers: following is a
subscription in the rider's own ntfy app to a public topic.

Topic: lastlift-<salt>-<station slug>. Off unless NOTIFY_MODE=ntfy (the default is a dry run that returns the
notice). Dedupe: the station's last notice is kept on a (:Notice {station}) node (never on the Station node, whose
name is in the full-text index: writing to it would shift search scores); an identical state sends nothing, and two
notices of the same kind are at least MIN_GAP_S apart.
"""
import hashlib
import os
import re
import time

import httpx

from .. import db, state
from ..wording import NEVER_SAY

SALT = os.environ.get("NOTIFY_SALT", "ll7c3a91")
MIN_GAP_S = 30 * 60
NTFY = "https://ntfy.sh"
SITE = os.environ.get("PUBLIC_SITE", "https://lastlift.vercel.app")


def topic(station_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", station_id.lower()).strip("-")
    return f"lastlift-{SALT}-{slug}"


def subscribe_url(station_id: str) -> str:
    return f"{NTFY}/{topic(station_id)}"


def compose(station_name: str, lost: list[dict], lifts: list[str]) -> dict:
    """lost: [{"platform": name, "dir": board|exit}] (empty = access restored)."""
    if lost:
        what = "; ".join(f"{x['platform']} ({'getting on' if x['dir'] == 'board' else 'getting off'})" for x in lost)
        body = (f"{station_name}: no step-free route in the open-data model for {what} while elevator "
                f"{', '.join(lifts)} is out. Check mbta.com/alerts/access before travelling.")
        return {"kind": "loss", "title": f"{station_name}: step-free access lost", "body": body, "priority": "4"}
    body = (f"{station_name}: step-free access is back in the open-data model (elevator {', '.join(lifts)} back in "
            "service per MBTA's feed). Check mbta.com/alerts/access before travelling.")
    return {"kind": "restore", "title": f"{station_name}: step-free access restored", "body": body, "priority": "3"}


def lint(text: str) -> list[str]:
    return [p for p in NEVER_SAY if re.search(p, text, re.I)]


Q_LAST = ("MATCH (s:Station {uid:$sid}) OPTIONAL MATCH (n:Notice {station:$sid}) "
          "RETURN n.hash, n.kind, n.at, s.name, n.lifts")
Q_SET = "MERGE (n:Notice {station:$sid}) SET n.hash = $h, n.kind = $k, n.at = $t, n.lifts = $l"
Q_OPEN_LOSSES = "MATCH (n:Notice) WHERE n.kind = 'loss' RETURN n.station, n.lifts"


def open_losses(scope: str) -> dict:
    g = db.client().select_graph(state.graph_name(scope))
    return {sid: list(lifts or []) for sid, lifts in g.ro_query(Q_OPEN_LOSSES).result_set}


def publish(scope: str, station_id: str, lost: list[dict], lifts: list[str], transport=None, now=None) -> dict:
    """Send (or dry-run) one notice if the station's state changed. Returns what happened."""
    g = db.client().select_graph(state.graph_name(scope))
    rs = g.ro_query(Q_LAST, {"sid": station_id}).result_set
    last_hash, last_kind, last_at, name, last_lifts = rs[0] if rs else (None, None, None, station_id, [])
    lifts = lifts or list(last_lifts or [])
    if not lost and last_kind != "loss":
        return {"sent": False, "reason": "nothing to restore"}
    msg = compose(name or station_id, lost, lifts)
    h = hashlib.sha256((msg["kind"] + msg["body"]).encode()).hexdigest()[:16]
    now = now if now is not None else time.time()
    if h == last_hash:
        return {"sent": False, "reason": "no change"}
    if last_kind == msg["kind"] and last_at and now - last_at < MIN_GAP_S:
        return {"sent": False, "reason": "rate limited"}
    problems = lint(msg["body"] + " " + msg["title"])
    if problems:
        return {"sent": False, "reason": f"wording: {problems}"}
    mode = os.environ.get("NOTIFY_MODE", "off")
    headers = {"Title": msg["title"], "Tags": "wheelchair", "Priority": msg["priority"],
               "Click": f"{SITE}/#/station/{station_id}"}
    if transport is not None or mode == "ntfy":
        post = transport or (lambda url, **kw: httpx.post(url, timeout=10, **kw))
        r = post(f"{NTFY}/{topic(station_id)}", content=msg["body"].encode(), headers=headers)
        if getattr(r, "status_code", 200) >= 300:
            return {"sent": False, "reason": f"ntfy HTTP {r.status_code}"}
        sent = True
    else:
        sent = False                                    # dry run: the notice is returned, not posted
    g.query(Q_SET, {"sid": station_id, "h": h, "k": msg["kind"], "t": now, "l": lifts})
    return {"sent": sent, "dry_run": not sent, "topic": topic(station_id), **msg}
