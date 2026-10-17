"""History time machine data (H4): web/public/m/history/days.json.

    python scripts/build_timemachine.py

- days: for every day since the replay's start (Boston local dates), the modelled lifts closed at any time that day
  and the platform-direction service hours without a step-free route that day (from data/history/replay.json);
- events: each closure episode that touches a day, with its start, end and recorded cause;
- collector: the live collector's 10-minute polls (data/alerts/), each with the lifts its elevator-closure alerts named.
The station graphs are today's: past days are today's layout with that day's closures, not the layout of the time.
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _nth_sunday(year, month, n):
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def boston(t):
    """US Eastern time without a tz database: UTC-4 from 02:00 on the second Sunday of March to 02:00 on the first
    Sunday of November (in force since 2007), otherwise UTC-5."""
    y = t.year
    dst_on = datetime.combine(_nth_sunday(y, 3, 2), datetime.min.time(), timezone.utc) + timedelta(hours=7)
    dst_off = datetime.combine(_nth_sunday(y, 11, 1), datetime.min.time(), timezone.utc) + timedelta(hours=6)
    return t + timedelta(hours=-4 if dst_on <= t < dst_off else -5)


OUT = ROOT / "web" / "public" / "m" / "history" / "days.json"


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    rep = json.loads((ROOT / "data" / "history" / "replay.json").read_text(encoding="utf-8"))
    modelled = {x["facility_id"] for x in json.loads((ROOT / "web" / "public" / "m" / "lifts.json").read_text(encoding="utf-8"))["lifts"]}
    start = date.fromisoformat(rep["from"])
    end = boston(ts(rep["archive_end"])).date()
    days = {}
    d = start
    while d < end:
        days[d.isoformat()] = {"closed": set(), "svc_h": round(rep["daily_svc_h"].get(d.isoformat(), 0.0), 1)}
        d += timedelta(days=1)
    events = {}
    for fid, eps in rep["episodes"].items():
        if fid not in modelled:
            continue
        for e in eps:
            a, b = boston(ts(e[0])), boston(ts(e[1]))
            day = max(a.date(), start)
            while day <= b.date() and day < end:
                key = day.isoformat()
                days[key]["closed"].add(fid)
                events.setdefault(key, []).append({"fid": fid, "start": e[0], "end": e[1], "cause": (e[4] or [""])[0]})
                day += timedelta(days=1)
    out_days = [{"d": k, "closed": sorted(v["closed"]), "svc_h": v["svc_h"]} for k, v in days.items()]

    # the live collector: rebuild the closed set at every 10-minute poll from the alert versions seen so far
    harvest = json.loads((ROOT / "data" / "alerts" / "HARVEST.json").read_text(encoding="utf-8"))
    versions = [json.loads(line) for line in (ROOT / "data" / "alerts" / "accessibility_alert_versions.jsonl")
                .read_text(encoding="utf-8").splitlines() if line.strip()]
    t0, t1 = ts(harvest["first_poll"]), ts(harvest["last_poll"])
    polls = []
    t = t0
    while t <= t1 + timedelta(seconds=1):
        latest = {}
        for v in versions:
            if ts(v["captured_at"]) <= t:
                latest[v["alert"]["id"]] = v["alert"]
        closed = set()
        for a in latest.values():
            at = a["attributes"]
            if at.get("effect") != "ELEVATOR_CLOSURE":
                continue
            active = any(ts(p["start"]) <= t and (p["end"] is None or t <= ts(p["end"])) for p in at.get("active_period", []))
            if active:
                closed |= {e["facility"] for e in at.get("informed_entity", []) if e.get("facility") in modelled}
        polls.append({"t": t.isoformat().replace("+00:00", "Z"), "closed": sorted(closed)})
        t += timedelta(minutes=10)
    doc = {"from": start.isoformat(), "to": (end - timedelta(days=1)).isoformat(), "days": out_days,
           "events": {k: sorted(v, key=lambda x: (x["start"], x["fid"])) for k, v in events.items()},
           "collector": {"source": harvest["source"], "polls": polls}}
    OUT.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(len(out_days), "days;", sum(len(v) for v in events.values()), "day-events;", len(polls), "polls;",
          round(OUT.stat().st_size / 1024), "KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
