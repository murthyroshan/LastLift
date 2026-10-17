"""Historical gold (H7): 20 archived closures, labelled blind by the author from MBTA's own text, compared with
what the model says for the lifts that were closed at that moment.

    python scripts/history_gold.py --make-sheet   # sample (seed in eval/sampling.json), write the label sheet
    python scripts/history_gold.py --score        # after the author's labels exist: agreement with a Wilson interval

The label sheet with MBTA's text is written to validation/_private/ (never committed). The committed file
validation/history_gold_ids.csv holds only ids, dates and a sha256 of each text. The author fills
validation/gold_history_author.csv (same columns as the live gold set, LABELLING_GUIDE.md) without looking at any
model output; the model's verdicts are computed only by --score.
"""
import argparse
import csv
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import history_replay as hr  # noqa: E402

VAL = ROOT / "validation"
PRIVATE = VAL / "_private"
LABELS = ["mbta_board_class", "mbta_exit_class", "mbta_named_elevators", "mbta_named_stations", "exp_verdict",
          "labeller_notes"]


def make_sheet():
    seed = json.loads((ROOT / "eval" / "sampling.json").read_text(encoding="utf-8"))["historical_gold_sample"]
    from lastlift import seed as seedmod
    net = json.loads((seedmod.latest_snapshot() / "network.json").read_text(encoding="utf-8"))
    texts = {r["alert_id"]: r for r in csv.DictReader((PRIVATE / "history_alerts.csv").open(encoding="utf-8"))}
    ws = [w for w in hr.load_windows() if w["end_recorded"] and w["start"] >= hr.LEDGER_FROM
          and w["facility_id"] in net["lifts"] and (texts.get(w["alert_id"]) or {}).get("description")]
    by_alert = {}
    for w in ws:
        by_alert.setdefault(w["alert_id"], w)
    pick = random.Random(seed["seed"]).sample(sorted(by_alert), seed["rows"])
    PRIVATE.mkdir(parents=True, exist_ok=True)
    with (PRIVATE / "history_gold_sheet.csv").open("w", encoding="utf-8", newline="\n") as fh, \
            (VAL / "history_gold_ids.csv").open("w", encoding="utf-8", newline="\n") as ids:
        sheet, idw = csv.writer(fh, lineterminator="\n"), csv.writer(ids, lineterminator="\n")
        sheet.writerow(["gold_id", "alert_id", "facility_ids", "start", "header", "description"] + LABELS)
        idw.writerow(["gold_id", "alert_id", "facility_ids", "start", "description_sha256"])
        for i, aid in enumerate(sorted(pick, key=int), 1):
            w, t = by_alert[aid], texts[aid]
            gid = f"H{i:02d}"
            sheet.writerow([gid, aid, t["facility_ids"], w["start"].strftime("%Y-%m-%dT%H:%MZ"), t["header"],
                            t["description"]] + [""] * len(LABELS))
            idw.writerow([gid, aid, t["facility_ids"], w["start"].strftime("%Y-%m-%dT%H:%MZ"),
                          hashlib.sha256(t["description"].encode()).hexdigest()])
    print(f"wrote {len(pick)} rows: validation/_private/history_gold_sheet.csv (label it; copy the label columns to "
          f"validation/gold_history_author.csv) and validation/history_gold_ids.csv")


def score():
    labels_path = VAL / "gold_history_author.csv"
    if not labels_path.is_file():
        print("no author labels yet (validation/gold_history_author.csv); nothing scored")
        return 1
    from lastlift import seed as seedmod
    from lastlift.cuts import wilson
    net = json.loads((seedmod.latest_snapshot() / "network.json").read_text(encoding="utf-8"))
    eps = hr.episodes(hr.merged_windows())
    labels = {r["gold_id"]: r for r in csv.DictReader(labels_path.open(encoding="utf-8"))}
    rows = []
    for r in csv.DictReader((VAL / "history_gold_ids.csv").open(encoding="utf-8")):
        t = datetime.fromisoformat(r["start"].replace("Z", ":00+00:00")) if r["start"].endswith("Z") else None
        t = t.astimezone(timezone.utc) if t else None
        fids = [f for f in r["facility_ids"].split(";") if f in net["lifts"]]
        closed = {f for f, es in eps.items() if f in net["lifts"] and any(s <= t < e for s, e, *_ in es)} | set(fids)
        lost = []
        for stop, p in net["platform"].items():
            for d in ("board", "exit"):
                sets = [set(x) for x in p[d].get("minimal") or []]
                if any(s <= closed for s in sets) and not any(s <= closed - set(fids) for s in sets):
                    lost.append(f"{stop}:{d}")
        model = "CANNOT_ASSESS" if not fids else ("LOSS" if lost else "NO_LOSS")
        lab = labels.get(r["gold_id"], {}).get("exp_verdict", "")
        rows.append({**r, "model_verdict": model, "model_lost": ";".join(lost), "exp_verdict": lab,
                     "match": "" if lab in ("", "CANNOT_ASSESS", "OUT_OF_SCOPE") or model == "CANNOT_ASSESS"
                     else ("Y" if (lab == "LOSS") == (model == "LOSS") else "N")})
    scored = [x for x in rows if x["match"]]
    agree = sum(x["match"] == "Y" for x in scored)
    lo, hi = wilson(agree, len(scored)) if scored else (0, 0)
    with (VAL / "history_gold_scored.csv").open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    claims_path = ROOT / "claims.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    claims.update({"hist_gold_scored": len(scored), "hist_gold_agree": agree,
                   "hist_gold_agree_wilson95": f"{round(lo * 100)}%, {round(hi * 100)}%"})
    claims_path.write_text(json.dumps(claims, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"historical gold: {agree}/{len(scored)} agree (Wilson 95% {lo:.2f}-{hi:.2f})")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-sheet", action="store_true")
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    sys.exit(make_sheet() if a.make_sheet else score())
