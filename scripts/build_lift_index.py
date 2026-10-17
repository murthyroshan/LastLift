"""Every modelled lift, for the what-if sandbox's picker: web/public/m/lifts.json (from the station mirror).

    python scripts/build_lift_index.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT / "web" / "public" / "m"


def main():
    lifts = {}
    for f in sorted((MIRROR / "station").glob("*.json")):
        b = json.loads(f.read_text(encoding="utf-8"))
        name = b["redundancy"]["data"]["name"]
        for n in b["graph"]["board"]["nodes"]:
            if n["kind"] == "lift" and n.get("facility_id"):
                lifts.setdefault(n["facility_id"], {"facility_id": n["facility_id"], "label": n["label"],
                                                    "station_id": f.stem, "station": name,
                                                    "status": n.get("status", "open"),
                                                    "last_lift": bool(n.get("last_lift"))})
    out = sorted(lifts.values(), key=lambda x: (x["station"], x["facility_id"]))
    (MIRROR / "lifts.json").write_text(json.dumps({"lifts": out}, indent=1, ensure_ascii=False) + "\n",
                                       encoding="utf-8", newline="\n")
    print(len(out), "lifts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
