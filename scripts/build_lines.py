"""Station order along each rapid-transit line, for the city sweep (MS2): web/public/m/lines.json.

    python scripts/build_lines.py

For every subway and light-rail route in the MBTA GTFS (route_type 0 or 1), the trip pattern with the most stops in
direction 0 is taken as the line's order, and its stops are mapped to their parent stations. Branches (the Red Line's
Ashmont and Braintree, the Green Line's B to E) are separate routes or patterns in the feed; a route with branches
gets one entry per distinct longest pattern ending. Names are the feed's route_long_name; no colours or logos.
"""
import csv
import io
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP = ROOT / "data" / "raw" / "MBTA_GTFS.zip"
OUT = ROOT / "web" / "public" / "m" / "lines.json"


def rows(z, name):
    return csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig"))


def main():
    z = zipfile.ZipFile(ZIP)
    routes = {r["route_id"]: r for r in rows(z, "routes.txt") if r.get("route_type") in ("0", "1")}
    parent = {s["stop_id"]: (s.get("parent_station") or s["stop_id"]) for s in rows(z, "stops.txt")}
    trips = {t["trip_id"]: (t["route_id"], t.get("shape_id") or t["trip_id"], t.get("trip_headsign", ""))
             for t in rows(z, "trips.txt") if t["route_id"] in routes and t.get("direction_id", "0") == "0"}
    seq = defaultdict(list)
    for st in rows(z, "stop_times.txt"):
        if st["trip_id"] in trips:
            seq[st["trip_id"]].append((int(st["stop_sequence"]), st["stop_id"]))
    patterns = defaultdict(dict)                      # route -> {tuple(stations): headsign}
    for tid, stops in seq.items():
        rid, _, head = trips[tid]
        stations = []
        for _, sid in sorted(stops):
            p = parent.get(sid, sid)
            if not stations or stations[-1] != p:
                stations.append(p)
        patterns[rid].setdefault(tuple(stations), head)
    lines = []
    for rid in sorted(patterns, key=lambda r: (routes[r].get("route_sort_order") or "", r)):
        pats = sorted(patterns[rid].items(), key=lambda kv: -len(kv[0]))
        seen_ends = set()
        for stations, head in pats:                   # the longest pattern per distinct terminus
            if stations[-1] in seen_ends or len(stations) < 3:
                continue
            if any(set(stations) <= set(p) for p, _ in pats if len(p) > len(stations)):
                continue
            seen_ends.add(stations[-1])
            lines.append({"route_id": rid, "name": routes[rid].get("route_long_name") or rid, "toward": head,
                          "stations": list(stations)})
    OUT.write_text(json.dumps({"lines": lines}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    for ln in lines:
        print(ln["route_id"], ln["name"], "->", ln["toward"], len(ln["stations"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
