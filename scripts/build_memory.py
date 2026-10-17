"""data/memory/disagreements.json from the committed live validation (validation/eval_live.csv): every lift where
MBTA's advice and the model only partly agreed or disagreed. Ids and verdict classes only, never MBTA's text.

    python scripts/build_memory.py
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    rows = []
    for r in csv.DictReader((ROOT / "validation" / "eval_live.csv").open(encoding="utf-8")):
        if r["match"] in ("PARTIAL", "DISAGREE"):
            for fid in r["facility_ids"].split(";"):
                rows.append({"facility_id": fid, "mbta": r["exp_verdict"], "model": r["model_verdict"],
                             "source": f"live validation {r['gold_id']}"})
    out = ROOT / "data" / "memory" / "disagreements.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(rows)} disagreements -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
