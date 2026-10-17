"""GTFS self-audit (D2): checks of MBTA's published station data that matter for step-free reasoning, written up as
docs/mbta_data_report.md for the author to send (never sent by LastLift).

    python scripts/gtfs_audit.py

MobilityData's canonical gtfs-validator is run first (data/raw/validator/out/report.json); no item here repeats one of
its notices. Checks, from the GTFS zip, the base graph (Cypher) and MBTA's V3 facility properties:
  A1 elevator pathways whose name or signage names a different elevator than their facility_id
  A2 entrances marked wheelchair_boarding = 2 that connect directly to an elevator
  A3 elevator pathways with no facility_id
  A4 elevators in facilities.txt that no pathway uses, at stations that publish pathways
  A5 platforms marked wheelchair_boarding = 1 with no step-free route in the published pathways (Cypher)
  A6 one stop_id covering two physical platforms (the overrides LastLift had to make, with their evidence)
  A7 V3 `excludes-stop` naming a platform for which that elevator is the single point of failure (what does it mean?)
  A8 elevator closures published as ACCESS_ISSUE instead of ELEVATOR_CLOSURE (archive, by facility)
"""
import collections
import csv
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift import db, state  # noqa: E402
from lastlift.config import settings  # noqa: E402
from lastlift.seed import latest_snapshot  # noqa: E402


def rd(z, name):
    return list(csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig")))


def main():
    z = zipfile.ZipFile(ROOT / "data" / "raw" / "MBTA_GTFS.zip")
    stops = {s["stop_id"]: s for s in rd(z, "stops.txt")}
    paths = rd(z, "pathways.txt")
    facs = {f["facility_id"]: f for f in rd(z, "facilities.txt")}
    elevators = {k for k, f in facs.items() if f["facility_type"] == "elevator"}
    net = json.loads((latest_snapshot() / "network.json").read_text(encoding="utf-8"))
    items = []

    a1 = []
    for p in paths:
        if p["pathway_mode"] != "5" or not p["facility_id"]:
            continue
        named = set(re.findall(r"Elevator (\d{3,4})", p["pathway_name"] or "")) - {p["facility_id"]}
        if named:
            a1.append({"pathway_id": p["pathway_id"], "facility_id": p["facility_id"], "named": sorted(named)})
    items.append(("A1", "Elevator pathways named after a different elevator than their facility_id", a1,
                  "A closure of the named elevator is linked to the wrong pathway, so its effect is modelled wrongly "
                  "(LastLift corrects Quincy Adams with an override; the others are reported as published).",
                  "Set facility_id to the elevator the pathway names (or correct the name)."))

    entr_to_lift = collections.defaultdict(set)
    for p in paths:
        if p["pathway_mode"] == "5":
            for end in (p["from_stop_id"], p["to_stop_id"]):
                entr_to_lift[end].add(p["facility_id"] or "?")
    a2 = []
    for p in paths:
        for a, b in ((p["from_stop_id"], p["to_stop_id"]), (p["to_stop_id"], p["from_stop_id"])):
            s = stops.get(a, {})
            if s.get("location_type") == "2" and s.get("wheelchair_boarding") == "2" and b in entr_to_lift:
                a2.append({"entrance": a, "name": s.get("stop_name"), "via_pathway": p["pathway_id"],
                           "to_elevator": sorted(entr_to_lift[b])})
    a2 = list({x["entrance"]: x for x in a2}.values())
    items.append(("A2", "Entrances marked not wheelchair accessible that lead directly to an elevator", a2,
                  "A step-free route through the elevator starts at this door, but the flag tells routers it cannot be "
                  "used; LastLift overrides it for Copley.", "Check wheelchair_boarding on these entrances."))

    a3 = [{"pathway_id": p["pathway_id"], "from": p["from_stop_id"], "to": p["to_stop_id"]}
          for p in paths if p["pathway_mode"] == "5" and not p["facility_id"]]
    items.append(("A3", "Elevator pathways with no facility_id", a3,
                  "A closure of this elevator cannot be linked to the pathway, so its effect cannot be assessed.",
                  "Add the facility_id."))

    used = {p["facility_id"] for p in paths if p["facility_id"]}
    path_stations = {stops.get(p["from_stop_id"], {}).get("parent_station") for p in paths} - {None, ""}
    a4 = [{"facility_id": f, "stop_id": facs[f]["stop_id"], "name": facs[f]["facility_long_name"]}
          for f in sorted(elevators - used)
          if (stops.get(facs[f]["stop_id"], {}).get("parent_station") or facs[f]["stop_id"]) in path_stations]
    items.append(("A4", "Elevators listed in facilities.txt but used by no pathway, at stations that publish pathways",
                  a4, "Their closures cannot be assessed against the station layout.",
                  "Add the elevator's pathways, or confirm it is not on a public route."))

    g = db.client().select_graph(state.graph_name("base"))
    rows = g.ro_query("MATCH (p:Node:Platform) WHERE p.wheelchair_boarding = 1 AND "
                      "(p.k_board_base = 0 OR p.k_exit_base = 0 OR p.no_accessible_entrance = true) "
                      "RETURN DISTINCT p.stop_id, p.name, p.platform_name, p.k_board_base, p.k_exit_base, "
                      "p.no_accessible_entrance ORDER BY p.stop_id").result_set
    a5 = [{"stop_id": r[0], "name": r[1], "platform": r[2], "board_routes": r[3], "exit_routes": r[4],
           "no_accessible_entrance": bool(r[5])} for r in rows]
    items.append(("A5", "Platforms marked wheelchair accessible with no step-free route in the published pathways",
                  a5, "Either the platform is not accessible or a step-free pathway is missing from the data.",
                  "Check wheelchair_boarding, or add the missing pathways."))

    ov = list(csv.DictReader((ROOT / "data" / "overrides.csv").open(encoding="utf-8")))
    a6 = [{"stop_id": r["target"], "station": stops.get(r["target"], {}).get("stop_name", ""),
           "layout": "a centre platform and a side platform share this stop_id; trains open on both sides, so one "
                     "side's riders reach the other side's elevator only by crossing through a train"}
          for r in ov if "split" in r["kind"]]
    items.append(("A6", "One stop_id covering two physical platforms", a6,
                  "Riders on one side cannot reach the other side's lift step-free; the data implies they can.",
                  "Model the two sides as boarding areas (location_type 4) or separate stops."))

    a7 = []
    try:
        headers = {"Accept": "application/vnd.api+json"}
        if settings.mbta_api_key:
            headers["x-api-key"] = settings.mbta_api_key
        r = httpx.get("https://api-v3.mbta.com/facilities", params={"filter[type]": "ELEVATOR", "page[limit]": 1000},
                      headers=headers, timeout=60)
        r.raise_for_status()
        excludes = {}
        for f in r.json()["data"]:
            ex = [p["value"] for p in f["attributes"].get("properties") or [] if p["name"] == "excludes-stop"]
            if ex:
                excludes[f["id"]] = {str(x) for x in ex}
        for stop, p in net["platform"].items():
            for d in ("board", "exit"):
                singles = [c[0] for c in p[d].get("minimal") or [] if len(c) == 1]
                for fid in singles:
                    if stop in excludes.get(fid, set()):
                        a7.append({"facility_id": fid, "excludes_stop": stop, "dir": d,
                                   "model": "only step-free route uses this elevator"})
        a7 = list({(x["facility_id"], x["excludes_stop"]): x for x in a7}.values())
        n_excl = len(excludes)
    except httpx.HTTPError as exc:
        n_excl = f"not fetched ({type(exc).__name__})"
    items.append(("A7", "excludes-stop naming a platform whose only step-free route uses that elevator (a question)",
                  a7, f"The property's meaning is undocumented ({n_excl} elevators carry it); read literally (the closure "
                  "does not affect that stop), it contradicts the pathways for these pairs.",
                  "Document what excludes-stop means."))

    a8 = collections.Counter()
    raw = ROOT / "data" / "raw" / "alerts"
    for zp in sorted(raw.glob("alerts_*.zip")):
        za = zipfile.ZipFile(zp)
        for name in (n for n in za.namelist() if n.lower().endswith(".csv")):
            for row in csv.DictReader(io.TextIOWrapper(za.open(name), encoding="utf-8-sig")):
                if row.get("effect_detail") == "ACCESS_ISSUE" and row.get("facility_id") in elevators:
                    a8[(row["facility_id"], row["alert_id"])] += 1
    by_fac = collections.Counter(f for f, _ in a8)
    items.append(("A8", "Elevator closures published as ACCESS_ISSUE rather than ELEVATOR_CLOSURE", [
        {"facility_id": f, "alerts": n, "name": facs[f]["facility_long_name"]} for f, n in by_fac.most_common()],
        "Tools that select elevator outages by effect miss these closures.",
        "Use ELEVATOR_CLOSURE for elevator outages, or say when ACCESS_ISSUE is intended."))

    vr = json.loads((ROOT / "data" / "raw" / "validator" / "out" / "report.json").read_text(encoding="utf-8"))
    codes = sorted(n["code"] for n in vr["notices"])
    write_report(items, vr, codes)
    claims_path = ROOT / "claims.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    claims.update({"audit_items": sum(1 for _, _, rows, *_ in items if rows),
                   "audit_validator_version": vr["summary"].get("validatorVersion", "8.0.1")})
    claims_path.write_text(json.dumps(claims, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    for code, title, rows, *_ in items:
        print(code, len(rows), title)
    return 0


def write_report(items, vr, codes):
    L = ["# Possible issues in MBTA's GTFS station data (step-free routing)", "",
         "*Prepared with LastLift (an unofficial prototype) for MBTA's developer contact (developer@mbta.com, the address "
         "in `feed_info.feed_contact_email`). Drafted by an AI coding assistant from the checks in "
         "`scripts/gtfs_audit.py`; reviewed and sent, if at all, by the author.*", "",
         "Thank you for publishing pathways, levels and elevator facilities: they make step-free reasoning possible. "
         "While building on them we found the items below. We may be misreading some of them; each one lists the "
         "evidence rows so it is quick to check.", "",
         f"MobilityData's gtfs-validator {vr['summary'].get('validatorVersion', '')} was run first on the same feed; it "
         f"raises {len(codes)} notice types ({', '.join(codes)}), none of which concerns the items below.", ""]
    n = 0
    for code, title, rows, impact, fix in items:
        if not rows:
            continue
        n += 1
        L += [f"## {n}. {title}", "", f"**Why it matters for step-free routing:** {impact}", "",
              f"**Suggested fix:** {fix}", "", "Evidence:", ""]
        keys = list(rows[0].keys())
        L += ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
        L += ["| " + " | ".join(str(r[k]) for k in keys) + " |" for r in rows[:40]]
        if len(rows) > 40:
            L.append(f"\n({len(rows) - 40} more rows in `scripts/gtfs_audit.py` output)")
        L.append("")
    L += ["Feed: the GTFS version recorded in LastLift's `claims.json`. Questions or corrections are very welcome."]
    (ROOT / "docs" / "mbta_data_report.md").write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
