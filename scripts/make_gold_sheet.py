"""Create the blind labelling sheet for the live gold set (validation/gold_live.csv).

Rows are the elevator-related accessibility alerts harvested from MBTA's V3 API. The human labeller
fills the mbta_* and exp_* columns from MBTA's own alert text only, before seeing any model output.
Model columns are added later by the evaluation script, never by hand.
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "alerts" / "accessibility_alert_versions.jsonl"
OUT = ROOT / "validation" / "gold_live.csv"
HUMAN_COLUMNS = ["mbta_board_class", "mbta_exit_class", "mbta_named_elevators", "mbta_named_stations",
                 "exp_verdict", "labeller_notes"]


def main():
    latest = {}
    for line in SRC.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        a = rec["alert"]
        attrs = a["attributes"]
        elevator = attrs["effect"] == "ELEVATOR_CLOSURE" or any(
            t in ("ELEVATOR", "ELEVATED_SUBPLATFORM") for t in rec.get("facility_types", {}).values())
        if attrs["effect"] in ("ELEVATOR_CLOSURE", "ACCESS_ISSUE") and elevator:
            if a["id"] not in latest or rec["captured_at"] > latest[a["id"]][0]:
                latest[a["id"]] = (rec["captured_at"], rec)
    rows = []
    for i, (alert_id, (_, rec)) in enumerate(sorted(latest.items()), 1):
        attrs = rec["alert"]["attributes"]
        facilities = sorted({ie.get("facility") for ie in attrs["informed_entity"] if ie.get("facility")})
        stations = sorted({ie.get("stop") for ie in attrs["informed_entity"]
                           if ie.get("stop", "").startswith("place-")})
        text = " ".join(x for x in (attrs.get("header"), attrs.get("description")) if x)
        rows.append({"gold_id": f"L{i:02d}", "alert_id": alert_id, "effect": attrs["effect"],
                     "facility_ids": ";".join(facilities), "stations": ";".join(stations),
                     "alert_updated_at": attrs.get("updated_at"),
                     "desc_sha256": hashlib.sha256(text.encode()).hexdigest()[:16],
                     "mbta_text": text, **{c: "" for c in HUMAN_COLUMNS}})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
