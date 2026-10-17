"""Build the lift closure history from MassDOT's "MBTA Service Alerts" CSV collections (stdlib only).

    python -I ingest/history.py --alerts data/raw/alerts --gtfs data/raw/MBTA_GTFS.zip

Inputs (downloaded by hand into data/raw/alerts/, never committed; sha256 recorded):
  alerts_2020-2023.zip, alerts_2024.zip, alerts_2025.zip, alerts_2026.zip  (monthly CSVs, one row per
  alert x active period x informed entity; a month's file lists the alert versions current in that month)
Outputs (committed, deterministic):
  data/history/windows.csv          one row per (alert, lift, active period): start, recorded end (if any),
                                     and two imputed ends for alerts that never recorded one
  data/history/service_windows.json first and last scheduled departure per station and day type
  data/history/meta.json            sources, counts, and the topology-drift lists (H8)

Rules (docs/model_rules.md, "History"):
  * a closure is a row with effect_detail ELEVATOR_CLOSURE and a facility id (ACCESS_ISSUE rows are counted as
    out of scope, not used);
  * the portal's timestamps are Boston local time despite their 'Z' suffix (see ts());
  * an alert's windows are those of its latest version (largest last_modified_dt);
  * recorded end = min(active period end, closed_dt) when either exists;
  * otherwise the end is imputed two ways: low = the latest last_modified_dt seen, high = the end of the last
    archive month that still lists the alert. Both are clipped to the archive's end.
"""
import argparse
import collections
import csv
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "history"
ITEMS = {  # ArcGIS item ids on the MassDOT open data portal (owner MBTAHUB_ADMIN)
    "2020-2023": "21ea74717cda441db3ae40d2cbc79a15", "2024": "f960d5089e164fb8b6c6936c70719d72",
    "2025": "ef115f7cf6684360b040b6d1d033eff0", "2026": "d233f1820cf54139bd18e75e30dd2c6c",
}
NA = {"", "NA", "N/A", "null", "None"}


def val(x):
    x = (x or "").strip()
    return None if x in NA else x


def ts(x):
    """The portal CSVs write Boston local time with a 'Z' suffix (checked against MBTA's V3 API timestamps, which
    carry their offset, via the LAMP archive: the same alerts differ by exactly the Eastern offset). So the clock
    time is read as Eastern local time and converted to UTC."""
    x = val(x)
    if not x:
        return None
    local = datetime.fromisoformat(x.rstrip("Z").split("+")[0]).replace(tzinfo=timezone.utc)
    return local - eastern_offset(local + timedelta(hours=5))      # UTC = local - offset (offset is -4 h or -5 h)


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else ""


def month_of(name):
    """'Alerts_2025/2025-03_ALERTS.csv' or 'Archive 2020-2023/2022/alerts_2022_06.csv' -> (2025, 3)."""
    stem = Path(name).stem
    digits = [p for p in stem.replace("-", "_").split("_") if p.isdigit()]
    return int(digits[0]), int(digits[1])


def month_end(y, m):
    return datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)


# --- Boston local time (US Eastern; rules fixed since 2007) ------------------------------------------------
def _nth_sunday(y, m, n):
    d = date(y, m, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def eastern_offset(t_utc: datetime) -> timedelta:
    y = t_utc.year
    start = datetime.combine(_nth_sunday(y, 3, 2), datetime.min.time(), timezone.utc) + timedelta(hours=7)
    end = datetime.combine(_nth_sunday(y, 11, 1), datetime.min.time(), timezone.utc) + timedelta(hours=6)
    return timedelta(hours=-4) if start <= t_utc < end else timedelta(hours=-5)


def read_alerts(folder: Path):
    alerts = {}
    stats = collections.Counter()
    sources = {}
    last_month = None
    for period in sorted(ITEMS):
        path = folder / f"alerts_{period}.zip"
        sources[period] = {"item_id": ITEMS[period], "file": path.name,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        z = zipfile.ZipFile(path)
        for name in sorted(n for n in z.namelist() if n.lower().endswith(".csv")):
            ym = month_of(name)
            last_month = max(last_month or ym, ym)
            for row in csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig")):
                detail = val(row.get("effect_detail"))
                fid = val(row.get("facility_id"))
                if detail != "ELEVATOR_CLOSURE":
                    if detail == "ACCESS_ISSUE" or (fid and val(row.get("effect")) == "ACCESS_ISSUE"):
                        stats["out_of_scope_access_issue_rows"] += 1
                    continue
                if not fid:
                    stats["no_facility_rows"] += 1
                    continue
                stats["rows"] += 1
                aid = row["alert_id"]
                a = alerts.setdefault(aid, {"versions": collections.defaultdict(set), "facilities": set(),
                                            "closed": None, "last_modified": None, "months": set(),
                                            "cause": None, "header": None, "description": None})
                lm = ts(row.get("last_modified_dt")) or ts(row.get("created_dt"))
                start = ts(row.get("active_period_start_dt"))
                if start:
                    a["versions"][lm].add((start, ts(row.get("active_period_end_dt"))))
                a["facilities"].add(fid)
                a["months"].add(ym)
                closed = ts(row.get("closed_dt"))
                if closed and (not a["closed"] or closed > a["closed"]):
                    a["closed"] = closed
                if lm and (not a["last_modified"] or lm >= a["last_modified"]):
                    a["last_modified"] = lm
                    a["cause"], a["header"], a["description"] = val(row.get("cause")), val(row.get("header")), \
                        val(row.get("description"))
    return alerts, stats, sources, last_month


def windows(alerts, archive_end):
    rows = []
    floor = datetime(2020, 1, 1, tzinfo=timezone.utc)
    for aid, a in sorted(alerts.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else kv[0]):
        if not a["versions"]:
            continue
        latest = max(a["versions"], key=lambda k: k or floor)
        last_seen = month_end(*max(a["months"]))
        for start, end in sorted(a["versions"][latest]):
            ends = [x for x in (end, a["closed"]) if x]
            recorded = min(ends) if ends else None
            low = max(a["last_modified"] or start, start)
            high = max(last_seen, low)
            s = max(start, floor)
            for fid in sorted(a["facilities"]):
                row = {"facility_id": fid, "alert_id": aid, "start": s,
                       "end_recorded": min(recorded, archive_end) if recorded else None,
                       "end_low": min(low, archive_end), "end_high": min(high, archive_end),
                       "cause": a["cause"] or ""}
                if (row["end_recorded"] or row["end_low"]) > s or row["end_high"] > s:
                    rows.append(row)
    return rows


def service_windows(gtfs: Path):
    """First and last scheduled departure (seconds after local midnight, may exceed 24 h) per parent station,
    for the snapshot's weekday (Thu 15 Oct 2026), Saturday 17 and Sunday 18 Oct 2026."""
    z = zipfile.ZipFile(gtfs)
    rd = lambda n: csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8-sig"))
    days = {"weekday": "20261015", "saturday": "20261017", "sunday": "20261018"}
    names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    cal = list(rd("calendar.txt"))
    exc = list(rd("calendar_dates.txt"))
    active = {}
    for kind, d in days.items():
        wd = names[date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday()]
        s = {c["service_id"] for c in cal if c["start_date"] <= d <= c["end_date"] and c[wd] == "1"}
        for x in exc:
            if x["date"] == d:
                (s.add if x["exception_type"] == "1" else s.discard)(x["service_id"])
        active[kind] = s
    trip_kinds = collections.defaultdict(list)
    for t in rd("trips.txt"):
        for kind, s in active.items():
            if t["service_id"] in s:
                trip_kinds[t["trip_id"]].append(kind)
    parent = {}
    for s in rd("stops.txt"):
        parent[s["stop_id"]] = s.get("parent_station") or s["stop_id"]
    win = collections.defaultdict(dict)
    reader = csv.reader(io.TextIOWrapper(z.open("stop_times.txt"), encoding="utf-8-sig"))
    head = next(reader)
    ti, di, si = head.index("trip_id"), head.index("departure_time"), head.index("stop_id")
    for row in reader:
        kinds = trip_kinds.get(row[ti])
        if not kinds or not row[di]:
            continue
        h, m, sec = map(int, row[di].split(":"))
        t = h * 3600 + m * 60 + sec
        st = parent.get(row[si], row[si])
        for kind in kinds:
            lo, hi = win[st].get(kind, (t, t))
            win[st][kind] = (min(lo, t), max(hi, t))
    return {st: {k: list(v) for k, v in sorted(w.items())} for st, w in sorted(win.items())}


def gtfs_elevators(gtfs: Path):
    z = zipfile.ZipFile(gtfs)
    return {f["facility_id"] for f in csv.DictReader(io.TextIOWrapper(z.open("facilities.txt"), encoding="utf-8-sig"))
            if f["facility_type"] == "elevator"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--alerts", default=str(ROOT / "data" / "raw" / "alerts"))
    ap.add_argument("--gtfs", default=str(ROOT / "data" / "raw" / "MBTA_GTFS.zip"))
    args = ap.parse_args(argv)
    alerts, stats, sources, last_month = read_alerts(Path(args.alerts))
    archive_end = month_end(*last_month)
    rows = windows(alerts, archive_end)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "windows.csv").open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["facility_id", "alert_id", "start", "end_recorded", "end_low", "end_high", "cause"])
        for r in rows:
            w.writerow([r["facility_id"], r["alert_id"], iso(r["start"]), iso(r["end_recorded"]),
                        iso(r["end_low"]), iso(r["end_high"]), r["cause"]])
    sw = service_windows(Path(args.gtfs))
    (OUT / "service_windows.json").write_text(json.dumps(sw, sort_keys=True, separators=(",", ":")) + "\n",
                                              encoding="utf-8", newline="\n")
    snap = sorted(p for p in (ROOT / "data" / "snapshots").iterdir() if (p / "MANIFEST.json").is_file())[-1]
    modelled = {json.loads(x).get("facility_id") for x in (snap / "nodes.jsonl").read_text(encoding="utf-8").splitlines()
                if '"LiftOut"' not in x and '"Lift"' in x and '"Node"' in x}
    modelled.discard(None)
    elevators = gtfs_elevators(Path(args.gtfs))
    archive_fids = {r["facility_id"] for r in rows}
    # private sheet for the historical gold (H7): MBTA's own text stays out of the repository
    private = ROOT / "validation" / "_private"
    private.mkdir(parents=True, exist_ok=True)
    with (private / "history_alerts.csv").open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["alert_id", "facility_ids", "header", "description"])
        for aid, a in sorted(alerts.items()):
            w.writerow([aid, ";".join(sorted(a["facilities"])), a["header"] or "", a["description"] or ""])
    meta = {
        "sources": sources, "archive_end": iso(archive_end), "rows_used": stats["rows"],
        "rows_without_facility": stats["no_facility_rows"],
        "out_of_scope_access_issue_rows": stats["out_of_scope_access_issue_rows"],
        "alerts": len({r["alert_id"] for r in rows}), "windows": len(rows),
        "windows_with_recorded_end": sum(1 for r in rows if r["end_recorded"]),
        "facilities_in_archive": len(archive_fids),
        "drift": {
            "archive_not_in_gtfs": sorted(archive_fids - elevators),
            "archive_not_in_model": sorted(archive_fids - modelled),
            "model_never_in_archive": sorted(modelled - archive_fids),
        },
        "description_sha256": {aid: hashlib.sha256((a["description"] or "").encode()).hexdigest()[:16]
                               for aid, a in sorted(alerts.items())},
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in meta.items() if k not in ("drift", "description_sha256", "sources")}, indent=1))
    print({k: len(v) for k, v in meta["drift"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
