"""MBTA LAMP's alert archive as a second source for the closure history (H2). Dev-only: needs pyarrow
(requirements-dev.txt); the app never reads parquet.

    python ingest/history_lamp.py --parquet data/raw/lamp/LAMP_RT_ALERTS.parquet

Source: https://performancedata.mbta.com/lamp/tableau/alerts/LAMP_RT_ALERTS.parquet (sha256 recorded).
Same rules as ingest/history.py (latest version per alert, recorded end = min(active end, closed), otherwise imputed
low = last modification). LAMP's timestamps are true UTC. It is updated daily, so it records the end of long-running
alerts that the portal's monthly files never closed, and holds alerts missing from them; it starts in 2019, the
portal in 2020. scripts/history_replay.py merges the two (portal first). Outputs:
  data/history/windows_lamp.csv   every LAMP closure window from 2019 to the portal archive's end
  data/history/lamp_meta.json
"""
import argparse
import collections
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "history"
URL = "https://performancedata.mbta.com/lamp/tableau/alerts/LAMP_RT_ALERTS.parquet"
COLS = ["id", "effect_detail", "cause", "last_modified_timestamp", "created_timestamp", "closed_timestamp",
        "active_period.start_timestamp", "active_period.end_timestamp", "informed_entity.facility_id"]


def utc(x):
    return datetime.fromtimestamp(x, timezone.utc) if x is not None else None


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else ""


def read(path):
    pf = pq.ParquetFile(path)
    alerts = {}
    rows = 0
    for i in range(pf.metadata.num_row_groups):
        t = pf.read_row_group(i, columns=COLS)
        t = t.filter(pc.and_(pc.equal(t["effect_detail"], "ELEVATOR_CLOSURE"),
                             pc.is_valid(t["informed_entity.facility_id"])))
        for r in t.to_pylist():
            rows += 1
            aid = str(r["id"])
            a = alerts.setdefault(aid, {"versions": collections.defaultdict(set), "fac": set(), "closed": None,
                                        "lm": None, "cause": None})
            lm = r["last_modified_timestamp"] or r["created_timestamp"]
            if r["active_period.start_timestamp"] is not None:
                a["versions"][lm].add((r["active_period.start_timestamp"], r["active_period.end_timestamp"]))
            a["fac"].add(r["informed_entity.facility_id"])
            if r["closed_timestamp"] and (a["closed"] is None or r["closed_timestamp"] > a["closed"]):
                a["closed"] = r["closed_timestamp"]
            if lm and (a["lm"] is None or lm >= a["lm"]):
                a["lm"], a["cause"] = lm, r["cause"]
    return alerts, rows


def windows(alerts, lo, hi, skip=()):
    out = []
    for aid, a in sorted(alerts.items(), key=lambda kv: int(kv[0])):
        if aid in skip or not a["versions"]:
            continue
        latest = max(a["versions"], key=lambda k: k or 0)
        for s, e in sorted(a["versions"][latest]):
            ends = [x for x in (e, a["closed"]) if x]
            rec = min(ends) if ends else None
            low = max(a["lm"] or s, s)
            start, er, el = utc(s), utc(rec) if rec else None, utc(low)
            if start >= hi or (er or el) <= lo:
                continue
            start = max(start, lo)
            er = min(er, hi) if er else None
            el = min(el, hi)
            for f in sorted(a["fac"]):
                if (er or el) > start:
                    out.append([f, aid, iso(start), iso(er), iso(el), iso(el), a["cause"] or ""])
    return out


def write(path, rows):
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["facility_id", "alert_id", "start", "end_recorded", "end_low", "end_high", "cause"])
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default=str(ROOT / "data" / "raw" / "lamp" / "LAMP_RT_ALERTS.parquet"))
    args = ap.parse_args(argv)
    path = Path(args.parquet)
    alerts, rows = read(path)
    end = datetime.fromisoformat(json.loads((OUT / "meta.json").read_text(encoding="utf-8"))["archive_end"]
                                 .replace("Z", "+00:00"))
    rows_out = windows(alerts, datetime(2019, 1, 1, tzinfo=timezone.utc), end)
    write(OUT / "windows_lamp.csv", rows_out)
    first = min(utc(min(s for v in a["versions"].values() for s, _ in v)) for a in alerts.values() if a["versions"])
    meta = {"source": URL, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "rows_used": rows,
            "alerts": len(alerts), "first_window_start": iso(first), "windows": len(rows_out),
            "windows_with_recorded_end": sum(1 for r in rows_out if r[3]), "until": iso(end)}
    (OUT / "lamp_meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n", encoding="utf-8",
                                        newline="\n")
    print(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
