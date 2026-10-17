"""The validation study (D1, validation/VALIDATION_PROTOCOL.md) over MBTA's alternative-service text (oracle O1).

    python scripts/validation_study.py --sheets   # add the audit sample and write the blind re-label sheet
    python scripts/validation_study.py --score    # after the author's labels: every output of the protocol

--sheets (before labelling):
  * marks a stratified random 20% of the rows where the regex pre-fill and the model agree (seed and strata in
    eval/sampling.json) in validation/_private/static_review.csv, column `audit` = Y; the author labels every row
    with review_required = Y or audit = Y, from the text alone;
  * writes validation/_private/static_relabel.csv: 30 rows (seed in eval/sampling.json), text only, to be labelled
    again blind at least 12 hours after the first labels (intra-rater kappa).
--score (after validation/gold_static.csv exists, built by scripts/static_sweep.py --make-gold):
  * unit: (lift, direction), the unit MBTA's text gives (Amendment 1 of the protocol);
  * 2x2 (model loses access / MBTA's text implies loss) with sensitivity, specificity, PPV, NPV and Wilson 95%
    intervals, plus a station-cluster bootstrap interval (1,000 resamples, seed 20261019); false-accessible cases;
  * reroute-class confusion matrix; named-lift recall (MBTA-named alternative lifts found on the model's routes);
  * precision of the unreviewed agreements (from the audit sample); intra-rater kappa (from the re-label sheet);
  * validation/static_errors.csv: every disagreement, with an empty `code` column for the E1-E9 taxonomy.
"""
import argparse
import collections
import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift.cuts import wilson  # noqa: E402

VAL = ROOT / "validation"
PRIVATE = VAL / "_private"
SAMPLING = json.loads((ROOT / "eval" / "sampling.json").read_text(encoding="utf-8"))
LOST = {"RIDE_AND_RETURN", "OTHER_STATION", "SHUTTLE_OR_BUS", "CROSS_THROUGH_TRAIN", "NO_ROUTE"}
CLASSES = ["IN_STATION", "RIDE_AND_RETURN", "OTHER_STATION", "SHUTTLE_OR_BUS", "CROSS_THROUGH_TRAIN", "NOT_STATED",
           "NO_ROUTE"]
BOOT_SEED, BOOT_N = 20261019, 1000


def read(path):
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def sheets():
    path = PRIVATE / "static_review.csv"
    rows = read(path)
    s = SAMPLING["static_sweep_agreement_sample"]
    rng = random.Random(s["seed"])
    strata = collections.defaultdict(list)
    for r in rows:
        if r["review_required"] == "N":
            strata[r[s["stratify_by"]]].append(r["facility_id"])
    pick = set()
    for key in sorted(strata):
        ids = sorted(strata[key], key=lambda x: (len(x), x))
        pick |= set(rng.sample(ids, max(1, round(s["fraction"] * len(ids)))))
    fields = list(rows[0].keys())
    if "audit" not in fields:
        fields.insert(fields.index("review_required") + 1, "audit")
    for r in rows:
        r["audit"] = "Y" if r["facility_id"] in pick else "N"
    write(path, rows, fields)
    k = SAMPLING["intra_rater_kappa_relabel"]
    to_label = sorted((r for r in rows if r["review_required"] == "Y" or r["audit"] == "Y"),
                      key=lambda r: (len(r["facility_id"]), r["facility_id"]))
    again = random.Random(k["seed"]).sample(to_label, k["rows"])
    write(PRIVATE / "static_relabel.csv", sorted(again, key=lambda r: (len(r["facility_id"]), r["facility_id"])),
          ["facility_id", "long_name", "stop", "text", "author_board_class", "author_exit_class",
           "author_named_elevators", "author_verdict", "author_notes"])
    print(f"audit sample: {len(pick)} of {sum(len(v) for v in strata.values())} agreement rows; rows to label: "
          f"{len(to_label)}; re-label sheet: {len(again)} rows (label at least {k['min_hours_after_first_label']} h "
          "after the first labels, without looking at them)")
    return 0


def kappa(a, b):
    labels = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(lab) / n) * (b.count(lab) / n) for lab in labels)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def prop(x, n):
    lo, hi = wilson(x, n) if n else (0, 0)
    return {"x": x, "n": n, "rate": round(x / n, 3) if n else None, "wilson95": [round(lo, 3), round(hi, 3)]}


def score():
    gold_path = VAL / "gold_static.csv"
    if not gold_path.is_file():
        print("no author labels yet (validation/gold_static.csv; run scripts/static_sweep.py --make-gold after "
              "labelling): nothing scored")
        return 1
    gold = {r["facility_id"]: r for r in read(gold_path)}
    model = {r["facility_id"]: r for r in read(VAL / "static_model.csv")}
    review = {r["facility_id"]: r for r in read(PRIVATE / "static_review.csv")}
    units = []
    for fid, g in gold.items():
        m = model.get(fid)
        if not m or m["model_verdict"] == "CANNOT_ASSESS" or g.get("author_verdict") in ("CANNOT_ASSESS", "OUT_OF_SCOPE"):
            continue
        for d in ("board", "exit"):
            gc, mc = g.get(f"author_{d}_class") or g.get(f"{d}_class"), m.get(f"model_{d}_class")
            if not gc or gc == "NOT_STATED" or not mc:
                continue
            units.append({"facility_id": fid, "station": m["stop"], "dir": d, "mbta_class": gc, "model_class": mc,
                          "mbta_lost": gc in LOST, "model_lost": mc in LOST,
                          "named": [x for x in (g.get("author_named_elevators") or "").split(";") if x],
                          "model_alt": [x for x in (m.get("model_alt_lifts") or "").split(";") if x]})
    tp = sum(u["mbta_lost"] and u["model_lost"] for u in units)
    fn = sum(u["mbta_lost"] and not u["model_lost"] for u in units)
    fp = sum(not u["mbta_lost"] and u["model_lost"] for u in units)
    tn = sum(not u["mbta_lost"] and not u["model_lost"] for u in units)

    def stats(us):
        a = sum(u["mbta_lost"] and u["model_lost"] for u in us)
        b = sum(u["mbta_lost"] and not u["model_lost"] for u in us)
        c = sum(not u["mbta_lost"] and u["model_lost"] for u in us)
        e = sum(not u["mbta_lost"] and not u["model_lost"] for u in us)
        return {"sensitivity": a / (a + b) if a + b else None, "specificity": e / (e + c) if e + c else None}

    by_station = collections.defaultdict(list)
    for u in units:
        by_station[u["station"]].append(u)
    rng = random.Random(BOOT_SEED)
    stations = sorted(by_station)
    boot = collections.defaultdict(list)
    for _ in range(BOOT_N):
        sample = [u for s in (rng.choice(stations) for _ in stations) for u in by_station[s]]
        for k, v in stats(sample).items():
            if v is not None:
                boot[k].append(v)
    ci = {k: [round(sorted(v)[int(0.025 * len(v))], 3), round(sorted(v)[int(0.975 * len(v)) - 1], 3)]
          for k, v in boot.items() if v}
    confusion = {a: {b: sum(1 for u in units if u["mbta_class"] == a and u["model_class"] == b) for b in CLASSES}
                 for a in CLASSES}
    named = [u for u in units if u["named"]]
    recall = sum(1 for u in named if set(u["named"]) & set(u["model_alt"]))
    audited = [review[f] for f in gold if review.get(f, {}).get("audit") == "Y"]
    audit_ok = sum(1 for r in audited if (gold[r["facility_id"]].get("author_verdict") or "") == r["prefill_verdict"])
    kap = None
    if (PRIVATE / "static_relabel.csv").is_file():
        again = [r for r in read(PRIVATE / "static_relabel.csv") if r.get("author_verdict")]
        if again:
            kap = {"rows": len(again), "kappa_verdict": kappa([gold[r["facility_id"]]["author_verdict"] for r in again],
                                                              [r["author_verdict"] for r in again])}
    errors = [{**{k: u[k] for k in ("facility_id", "station", "dir", "mbta_class", "model_class")}, "code": "",
               "note": ""} for u in units if u["mbta_lost"] != u["model_lost"] or u["mbta_class"] != u["model_class"]]
    write(VAL / "static_errors.csv", errors, ["facility_id", "station", "dir", "mbta_class", "model_class", "code", "note"])
    doc = {"units": len(units), "two_by_two": {"tp": tp, "fn": fn, "fp": fp, "tn": tn},
           "sensitivity": prop(tp, tp + fn), "specificity": prop(tn, tn + fp), "ppv": prop(tp, tp + fp),
           "npv": prop(tn, tn + fn), "station_bootstrap95": ci,
           "false_accessible": [f"{u['facility_id']} {u['dir']}" for u in units if u["mbta_lost"] and not u["model_lost"]],
           "reroute_confusion": confusion, "named_lift_recall_loose": prop(recall, len(named)),
           "audit_precision": prop(audit_ok, len(audited)), "intra_rater": kap, "disagreements": len(errors)}
    (VAL / "static_study.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8",
                                           newline="\n")
    print(json.dumps({k: v for k, v in doc.items() if k != "reroute_confusion"}, indent=1))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", action="store_true")
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    sys.exit(sheets() if a.sheets else score())
