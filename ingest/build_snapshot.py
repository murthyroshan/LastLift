"""Build the deterministic LastLift graph snapshot from a pinned MBTA GTFS zip.

    python -I ingest/build_snapshot.py --gtfs data/raw/MBTA_GTFS.zip --date 2026-10-15

Writes data/snapshots/<date>/{nodes.jsonl, edges.jsonl, MANIFEST.json}. Stdlib only; the same
inputs always produce byte-identical outputs (sorted rows, sorted keys, LF endings, no timestamps).
Modelling rules are documented in docs/model_rules.md.
"""
import argparse
import collections
import csv
import hashlib
import io
import json
import math
import os
import sys
import zipfile

BIG = 1_000_000
RULES_VERSION = 1
WALK_MODES = {"1": "walk", "3": "walk"}            # walkway, moving sidewalk
GATE_MODES = {"6": "gate", "7": "gate"}            # fare gate, exit gate (assumed accessible)
STEP_MODES = {"2": "stairs", "4": "escalator"}     # never step-free; kept for explanations
ELEVATOR = "5"
GATE_WT, STREET_WT, LIFT_DEFAULT_WT, BOARDING_PENALTY = 10, 60, 60, 300
RIDE_ROUTE_TYPES = {"0", "1", "2"}                 # light rail, subway, commuter rail


def merged_complex(station_id):
    # The Winter St Concourse links Park St and Downtown Crossing with step-free pathways.
    return "pktrm+dwnxg" if station_id in ("place-pktrm", "place-dwnxg") else station_id


def read_csv(z, name):
    return list(csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig")))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_overrides(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8", newline="")))
    by_kind = collections.defaultdict(list)
    for r in rows:
        by_kind[r["kind"]].append(r)
    return rows, by_kind


def build(gtfs_path, overrides_path, service_date):
    z = zipfile.ZipFile(gtfs_path)
    stops = {r["stop_id"]: r for r in read_csv(z, "stops.txt")}
    facilities = {r["facility_id"]: r for r in read_csv(z, "facilities.txt")}
    pathways = read_csv(z, "pathways.txt")
    routes = {r["route_id"]: r for r in read_csv(z, "routes.txt")}
    route_patterns = read_csv(z, "route_patterns.txt")
    feed = read_csv(z, "feed_info.txt")[0]
    ov_rows, ov = load_overrides(overrides_path)
    applied = collections.Counter()

    def parent(stop_id):
        s = stops.get(stop_id, {})
        return s.get("parent_station") or (stop_id if s.get("location_type") == "1" else "")

    # --- overrides: facility fixes --------------------------------------------------------
    fix = {r["target"]: r["value"] for r in ov["facility_fix"]}
    for p in pathways:
        if p["pathway_id"] in fix:
            p["facility_id"] = fix[p["pathway_id"]]
            applied[f"facility_fix:{p['pathway_id']}"] += 1

    # --- overrides: split platforms into physical halves ------------------------------------
    centre_of = {}   # split stop -> set of nodes that belong to its centre half
    for r in ov["split_platform"]:
        centre_of[r["target"]] = set(r["value"].split(";"))

    def remap(stop_id, other):
        if stop_id in centre_of and other in centre_of[stop_id]:
            applied[f"split_platform:{stop_id}"] += 1
            return f"{stop_id}#centre"
        return stop_id

    for p in pathways:
        a, b = p["from_stop_id"], p["to_stop_id"]
        p["from_stop_id"], p["to_stop_id"] = remap(a, b), remap(b, a)

    halves = {s: [s, f"{s}#centre"] for s in centre_of}

    def base_stop(uid):
        return uid.split("#", 1)[0]

    # --- overrides: entrances treated as accessible sources ---------------------------------
    accessible_override = {r["target"] for r in ov["entrance_accessible"] if r["value"] == "1"}

    # --- lift units: one per facility per connected component of its own pathways ----------
    elevator_rows = [p for p in pathways if p["pathway_mode"] == ELEVATOR]

    def facility_of(p):
        if p["facility_id"]:
            return p["facility_id"]
        a, b = sorted((p["from_stop_id"], p["to_stop_id"]))
        return f"nofac-{a}"

    by_facility = collections.defaultdict(list)
    for p in elevator_rows:
        by_facility[facility_of(p)].append(p)
    unit_of, unit_facility = {}, {}
    for fac, rows in sorted(by_facility.items()):
        parent_map = {}

        def find(x):
            while parent_map.setdefault(x, x) != x:
                parent_map[x] = parent_map[parent_map[x]]
                x = parent_map[x]
            return x

        for p in rows:
            parent_map[find(p["from_stop_id"])] = find(p["to_stop_id"])
        comps = sorted({find(n) for p in rows for n in (p["from_stop_id"], p["to_stop_id"])})
        for p in rows:
            i = comps.index(find(p["from_stop_id"]))
            unit = fac if len(comps) == 1 else f"{fac}#{i + 1}"
            unit_of[p["pathway_id"]] = unit
            unit_facility[unit] = fac

    # --- edges -------------------------------------------------------------------------------
    sf, step = {}, {}

    def add_sf(a, b, kind, wt, pathway_id=None, unit=None, cap=BIG):
        key = (a, b)
        e = sf.get(key)
        if e is None:
            sf[key] = e = {"kind": kind, "cap": cap, "wt": wt, "pathway_ids": set()}
            if unit:
                e["unit"] = unit
                e["facility_id"] = unit_facility[unit]
        else:
            e["wt"] = min(e["wt"], wt)
        if pathway_id:
            e["pathway_ids"].add(pathway_id)

    for p in pathways:
        mode, a, b = p["pathway_mode"], p["from_stop_id"], p["to_stop_id"]
        length = float(p["length"] or 0)
        if mode in WALK_MODES:
            wt = int(p["wheelchair_traversal_time"] or p["traversal_time"] or math.ceil(length) or GATE_WT)
            add_sf(a, b, "walk", max(1, wt), p["pathway_id"])
        elif mode in GATE_MODES:
            add_sf(a, b, "gate", GATE_WT, p["pathway_id"])
        elif mode == ELEVATOR:
            unit = unit_of[p["pathway_id"]]
            lin, lout = f"lift:{unit}", f"lift:{unit}:out"
            wt = int(p["wheelchair_traversal_time"] or LIFT_DEFAULT_WT)
            add_sf(a, lin, "lift_access", 1, p["pathway_id"])
            add_sf(lout, b, "lift_access", 1, p["pathway_id"])
            add_sf(lin, lout, "lift", wt, p["pathway_id"], unit=unit, cap=1)
        elif mode in STEP_MODES:
            key = (a, b)
            e = step.setdefault(key, {"kind": STEP_MODES[mode], "pathway_ids": set(),
                                      "facility_id": p["facility_id"] or None,
                                      "stair_count": int(p["stair_count"]) if p["stair_count"] else None})
            e["pathway_ids"].add(p["pathway_id"])

    path_nodes = {n for key in list(sf) + list(step) for n in key if not n.startswith("lift:")}

    # --- streets: one virtual 'outside' node per station with an accessible entrance --------
    streets = {}
    for n in sorted(path_nodes):
        s = stops.get(base_stop(n), {})
        if s.get("location_type") == "2" and (s.get("wheelchair_boarding") == "1" or n in accessible_override):
            if n in accessible_override:
                applied[f"entrance_accessible:{n}"] += 1
            st = parent(n)
            streets[st] = f"street:{st}"
            add_sf(streets[st], n, "street", STREET_WT)
            add_sf(n, streets[st], "street", STREET_WT)

    # --- service day, departures (ridership proxy) and train-ride edges ---------------------
    day = service_date.replace("-", "")
    weekday = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][
        __import__("datetime").date(int(day[:4]), int(day[4:6]), int(day[6:])).weekday()]
    active = {c["service_id"] for c in read_csv(z, "calendar.txt")
              if c["start_date"] <= day <= c["end_date"] and c[weekday] == "1"}
    for x in read_csv(z, "calendar_dates.txt"):
        if x["date"] == day:
            (active.add if x["exception_type"] == "1" else active.discard)(x["service_id"])
    trip_active = {t["trip_id"] for t in read_csv(z, "trips.txt") if t["service_id"] in active}
    reps = {r["representative_trip_id"]: r for r in route_patterns
            if routes[r["route_id"]]["route_type"] in RIDE_ROUTE_TYPES and r["route_pattern_typicality"] in ("1", "2")}
    deps = collections.Counter()
    seqs = collections.defaultdict(list)
    reader = csv.reader(io.TextIOWrapper(z.open("stop_times.txt"), encoding="utf-8-sig"))
    head = next(reader)
    ti, ai, di, si, qi = (head.index(k) for k in ("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"))
    for row in reader:
        if row[ti] in trip_active:
            deps[row[si]] += 1
        if row[ti] in reps:
            seqs[row[ti]].append((int(row[qi]), row[si], row[ai], row[di]))

    def seconds(t):
        h, m, s = map(int, t.split(":"))
        return h * 3600 + m * 60 + s

    ride = {}
    ride_stops = set()
    for trip_id in sorted(seqs):
        seq = sorted(seqs[trip_id])
        rp = reps[trip_id]
        for (_, a, _, dep), (_, b, arr, _) in zip(seq, seq[1:]):
            wt = max(30, seconds(arr) - seconds(dep))
            for ha in halves.get(a, [a]):
                for hb in halves.get(b, [b]):
                    e = ride.setdefault((ha, hb), {"wt": wt, "routes": set(),
                                                   "route_type": routes[rp["route_id"]]["route_type"]})
                    e["wt"] = min(e["wt"], wt)
                    e["routes"].add(rp["route_id"])
            ride_stops.update(halves.get(a, [a]) + halves.get(b, [b]))

    for (a, b), e in sf.items():
        if e["kind"] in ("walk", "gate", "lift_access") and b in ride_stops:
            e["wt"] += BOARDING_PENALTY

    # --- nodes ---------------------------------------------------------------------------------
    nodes = {}

    def cx_of(stop_uid):
        return merged_complex(parent(base_stop(stop_uid)))

    for st_id, s in stops.items():
        if s["location_type"] == "1":
            nodes[st_id] = {"labels": ["Station"], "uid": st_id, "name": s["stop_name"],
                            "municipality": s.get("municipality") or None, "cx": merged_complex(st_id),
                            "lat": float(s["stop_lat"]) if s["stop_lat"] else None,
                            "lon": float(s["stop_lon"]) if s["stop_lon"] else None,
                            "has_pathways": False, "has_street": st_id in streets}

    for uid in sorted(path_nodes):
        s = stops[base_stop(uid)]
        lt = s["location_type"]
        common = {"uid": uid, "name": s["stop_name"], "station_id": parent(base_stop(uid)), "cx": cx_of(uid)}
        if lt == "0":
            row = dict(common, labels=["Node", "Platform"], stop_id=base_stop(uid), modelled=True,
                       platform_name=s.get("platform_name") or None, wheelchair_boarding=int(s["wheelchair_boarding"] or 0),
                       is_rail=uid in ride_stops, deps_day=deps.get(base_stop(uid), 0))
            if base_stop(uid) in centre_of:
                row["half"] = "centre" if uid.endswith("#centre") else "side"
        elif lt == "2":
            wb = 1 if uid in accessible_override else int(s["wheelchair_boarding"] or 0)
            row = dict(common, labels=["Node", "Entrance"], wheelchair_boarding=wb,
                       accessible_source=wb == 1, overridden=uid in accessible_override)
        else:
            row = dict(common, labels=["Node", "Generic"])
        nodes[uid] = row
        if row["station_id"] in nodes and "Station" in nodes[row["station_id"]]["labels"]:
            nodes[row["station_id"]]["has_pathways"] = True

    for st_id, uid in streets.items():
        nodes[uid] = {"labels": ["Node", "Street"], "uid": uid, "name": f"Street ({stops[st_id]['stop_name']})",
                      "station_id": st_id, "cx": merged_complex(st_id)}

    for unit, fac in sorted(unit_facility.items()):
        f = facilities.get(fac, {})
        access = sorted(a for (a, b) in sf if b == f"lift:{unit}")
        st = parent(base_stop(access[0])) if access else ""
        base = {"station_id": st, "cx": merged_complex(st)}
        nodes[f"lift:{unit}"] = dict(base, labels=["Node", "Lift"], uid=f"lift:{unit}", unit=unit, facility_id=fac,
                                     name=f.get("facility_long_name") or f"Elevator {fac}",
                                     short_name=f.get("facility_short_name") or None, modelled=True)
        nodes[f"lift:{unit}:out"] = dict(base, labels=["Node", "LiftOut"], uid=f"lift:{unit}:out", unit=unit)

    modelled_facilities = set(unit_facility.values())
    for fac, f in sorted(facilities.items()):
        if f["facility_type"] == "elevator" and fac not in modelled_facilities:
            st = parent(f["stop_id"]) if f["stop_id"] in stops else f["stop_id"]
            nodes[f"lift:{fac}"] = {"labels": ["Lift"], "uid": f"lift:{fac}", "unit": fac, "facility_id": fac,
                                    "name": f.get("facility_long_name") or f"Elevator {fac}",
                                    "short_name": f.get("facility_short_name") or None,
                                    "station_id": st, "cx": merged_complex(st), "modelled": False}

    for uid in sorted(ride_stops):
        if uid not in nodes:
            s = stops[base_stop(uid)]
            nodes[uid] = {"labels": ["Platform"], "uid": uid, "stop_id": base_stop(uid), "name": s["stop_name"],
                          "platform_name": s.get("platform_name") or None, "station_id": parent(base_stop(uid)),
                          "modelled": False, "is_rail": True, "deps_day": deps.get(base_stop(uid), 0)}

    # --- edge rows -------------------------------------------------------------------------------
    edges = []
    for (a, b), e in sf.items():
        row = {"type": "SF", "a": a, "b": b, "eid": f"SF:{a}>{b}", "kind": e["kind"], "cap": e["cap"],
               "wt": e["wt"], "pathway_ids": sorted(e["pathway_ids"])}
        if "unit" in e:
            row.update(unit=e["unit"], facility_id=e["facility_id"])
        edges.append(row)
    for (a, b), e in step.items():
        edges.append({"type": "STEP", "a": a, "b": b, "eid": f"STEP:{a}>{b}", "kind": e["kind"],
                      "pathway_ids": sorted(e["pathway_ids"]), "facility_id": e["facility_id"],
                      "stair_count": e["stair_count"]})
    for (a, b), e in ride.items():
        edges.append({"type": "RIDE", "a": a, "b": b, "eid": f"RIDE:{a}>{b}", "wt": e["wt"],
                      "routes": sorted(e["routes"]), "route_type": e["route_type"]})
    for uid, n in nodes.items():
        st = n.get("station_id")
        if st in nodes and "Station" in nodes[st]["labels"] and uid != st:
            rel = {"Entrance": "HAS_ENTRANCE", "Platform": "HAS_PLATFORM", "Lift": "HAS_LIFT"}
            for label, t in rel.items():
                if label in n["labels"] and "Node" in n["labels"] or (label == "Lift" and "Lift" in n["labels"]):
                    if label in n["labels"]:
                        edges.append({"type": t, "a": st, "b": uid, "eid": f"{t}:{st}>{uid}"})

    for r in ov_rows:
        key = f"{r['kind']}:{r['target']}"
        if not applied.get(key):
            raise SystemExit(f"override {r['id']} ({key}) matched nothing: GTFS changed or override is wrong")

    meta = {"feed_version": feed["feed_version"], "service_date": service_date, "rules_version": RULES_VERSION,
            "big": BIG, "overrides_applied": dict(sorted(applied.items()))}
    return nodes, edges, meta


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--gtfs", default="data/raw/MBTA_GTFS.zip")
    ap.add_argument("--overrides", default="data/overrides.csv")
    ap.add_argument("--date", default="2026-10-15")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    out = args.out or os.path.join("data", "snapshots", args.date)
    os.makedirs(out, exist_ok=True)

    nodes, edges, meta = build(args.gtfs, args.overrides, args.date)
    node_rows = sorted(nodes.values(), key=lambda n: (",".join(n["labels"]), n["uid"]))
    edge_rows = sorted(edges, key=lambda e: (e["type"], e["a"], e["b"]))
    write_jsonl(os.path.join(out, "nodes.jsonl"), node_rows)
    write_jsonl(os.path.join(out, "edges.jsonl"), edge_rows)

    files = {name: sha256_file(os.path.join(out, name)) for name in ("nodes.jsonl", "edges.jsonl")}
    seed = hashlib.sha256("".join(f"{k}:{v}\n" for k, v in sorted(files.items())).encode()).hexdigest()
    label_counts = collections.Counter(",".join(n["labels"]) for n in node_rows)
    type_counts = collections.Counter(e["type"] for e in edge_rows)
    sf_kinds = collections.Counter(e["kind"] for e in edge_rows if e["type"] == "SF")
    manifest = dict(meta, source={"name": "MBTA GTFS", "url": "https://cdn.mbta.com/MBTA_GTFS.zip",
                                  "sha256": sha256_file(args.gtfs)},
                    files=files, seed_sha256=seed,
                    counts={"nodes_by_labels": dict(sorted(label_counts.items())),
                            "edges_by_type": dict(sorted(type_counts.items())),
                            "sf_edges_by_kind": dict(sorted(sf_kinds.items())),
                            "nodes": len(node_rows), "edges": len(edge_rows)})
    with open(os.path.join(out, "MANIFEST.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print(json.dumps(manifest["counts"], indent=1))
    print("seed_sha256", seed)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
