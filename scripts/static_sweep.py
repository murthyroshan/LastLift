"""Static sweep: every MBTA elevator that has published alternate-service text, model vs text.

    python scripts/static_sweep.py              # fetch, pre-fill, run the model, write the files below
    python scripts/static_sweep.py --make-gold  # after the author has labelled the flagged rows

MBTA's `alternate-service-text` facility property says what riders should do when each elevator is
out. That text is used here only to validate; it is never displayed, never loaded into the served
graph and never committed. Outputs:

  validation/_private/static_review.csv  (gitignored) text + regex pre-fill + blank author columns.
      This is the blind sheet the author labels: it never shows the model's verdict.
  validation/static_prefill.csv          (committed) facility, text sha256, pre-fill, review flag.
  validation/static_model.csv            (committed) the model's verdict for each facility.

A row is flagged for author review when the pre-fill is incomplete (a direction not stated or not
recognised) or the pre-fill verdict differs from the model's. The author's labels go in
validation/gold_static.csv; scripts/eval.py scores the sweep only from that file.
"""
import csv
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift import verdict  # noqa: E402
from lastlift.config import settings  # noqa: E402

PRIVATE = ROOT / "validation" / "_private"
PREFILL = ROOT / "validation" / "static_prefill.csv"
MODEL = ROOT / "validation" / "static_model.csv"
LOST = {"RIDE_AND_RETURN", "OTHER_STATION", "SHUTTLE_OR_BUS", "CROSS_THROUGH_TRAIN"}


def fetch():
    req = urllib.request.Request("https://api-v3.mbta.com/facilities?filter[type]=ELEVATOR&page[limit]=500",
                                 headers={"x-api-key": settings.mbta_api_key})
    data = json.load(urllib.request.urlopen(req, timeout=60))["data"]
    out = []
    for f in data:
        text = next((p["value"] for p in f["attributes"].get("properties", []) if p["name"] == "alternate-service-text"), None)
        if text:
            stop = (f.get("relationships", {}).get("stop", {}).get("data") or {}).get("id")
            out.append({"facility_id": f["id"], "long_name": f["attributes"].get("long_name"), "stop": stop, "text": text})
    return sorted(out, key=lambda r: int(r["facility_id"]) if r["facility_id"].isdigit() else 10**9)


def classify(part):
    t = part.lower()
    if not t.strip():
        return "NOT_STATED"
    if "cross through the train" in t:
        return "CROSS_THROUGH_TRAIN"
    if "shuttle" in t or re.search(r"\bbus(es)?\b", t):
        return "SHUTTLE_OR_BUS"
    if re.search(r"\btrain\b", t) and re.search(r"\b(then|transfer|back)\b", t):
        return "RIDE_AND_RETURN"
    if re.search(r"\b(use|take) [\w./' -]*?elevator \d{3,4}", t) or re.search(r"\b(ramp|passageway)\b", t):
        return "IN_STATION"
    return "UNRECOGNISED"


def prefill(fid, text):
    exit_m = re.search(r"to exit\b(.*?)(?=to board\b|$)", text, re.IGNORECASE | re.DOTALL)
    board_m = re.search(r"to board\b(.*?)(?=to exit\b|$)", text, re.IGNORECASE | re.DOTALL)
    if exit_m or board_m:
        b = classify(board_m.group(1) if board_m else "")
        x = classify(exit_m.group(1) if exit_m else "")
    else:                                   # one instruction for both directions
        b = x = classify(text)
    named = sorted({n for n in re.findall(r"[Ee]levators? (\d{3,4})", text) if n != fid}, key=int)
    if b in LOST or x in LOST:
        v = "LOSS"
    elif b == x == "IN_STATION":
        v = "NO_LOSS"
    else:
        v = "UNCLEAR"
    return {"prefill_board_class": b, "prefill_exit_class": x, "prefill_named_elevators": ";".join(named),
            "prefill_verdict": v}


def make_gold():
    """validation/gold_static.csv from the author's sheet: author labels for flagged rows and for the audit sample
    (scripts/validation_study.py --sheets; all must be filled), the regex pre-fill for the rest, marked as such.
    Never copies the alternate-service text."""
    sheet = list(csv.DictReader((PRIVATE / "static_review.csv").open(encoding="utf-8")))
    labelled = lambda r: r["review_required"] == "Y" or r.get("audit") == "Y"   # noqa: E731
    missing = [r["facility_id"] for r in sheet if labelled(r) and not r["author_verdict"].strip()]
    if missing:
        print(f"{len(missing)} rows to label have no author_verdict yet, e.g. {missing[:5]}")
        return 1
    out = []
    for r in sheet:
        if labelled(r):
            lab = {"author_board_class": r["author_board_class"], "author_exit_class": r["author_exit_class"],
                   "author_named_elevators": r["author_named_elevators"], "author_verdict": r["author_verdict"],
                   "labelled_by": "author (from MBTA alternate-service text)", "notes": r["author_notes"]}
        else:
            lab = {"author_board_class": r["prefill_board_class"], "author_exit_class": r["prefill_exit_class"],
                   "author_named_elevators": r["prefill_named_elevators"], "author_verdict": r["prefill_verdict"],
                   "labelled_by": "regex prefill, not reviewed (matched the model's verdict)", "notes": ""}
        out.append({"facility_id": r["facility_id"], "text_sha256": r["text_sha256"], **lab})
    with (ROOT / "validation" / "gold_static.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"validation/gold_static.csv: {len(out)} rows ({sum(labelled(r) for r in sheet)} author-labelled)")
    return 0


def main():
    if "--make-gold" in sys.argv:
        return make_gold()
    rows = fetch()
    PRIVATE.mkdir(parents=True, exist_ok=True)
    review, pre, model = [], [], []
    for i, r in enumerate(rows, 1):
        p = prefill(r["facility_id"], r["text"])
        m = verdict.assess([r["facility_id"]])
        flag = (p["prefill_verdict"] == "UNCLEAR" or "UNRECOGNISED" in (p["prefill_board_class"], p["prefill_exit_class"])
                or (m["verdict"] != "CANNOT_ASSESS" and p["prefill_verdict"] != m["verdict"]))
        sha = hashlib.sha256(r["text"].encode("utf-8")).hexdigest()[:16]
        base = {"facility_id": r["facility_id"], "long_name": r["long_name"], "stop": r["stop"], "text_sha256": sha}
        pre.append({**base, **p, "review_required": "Y" if flag else "N"})
        review.append({**base, "text": r["text"], **p, "review_required": "Y" if flag else "N",
                       "author_board_class": "", "author_exit_class": "", "author_named_elevators": "",
                       "author_verdict": "", "author_notes": ""})
        model.append({**base, "model_verdict": m["verdict"], "model_board_class": m["classes"].get("board", ""),
                      "model_exit_class": m["classes"].get("exit", ""), "model_alt_lifts": ";".join(m["alt_lifts"]),
                      "model_entrances_cut": ";".join(m["entrances_cut"])})
        print(f"[{i}/{len(rows)}] {r['facility_id']} prefill {p['prefill_verdict']} model {m['verdict']}"
              f"{' REVIEW' if flag else ''}", flush=True)
    for path, data in ((PRIVATE / "static_review.csv", review), (PREFILL, pre), (MODEL, model)):
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0].keys()), lineterminator="\n")
            w.writeheader()
            w.writerows(data)
    flagged = sum(r["review_required"] == "Y" for r in pre)
    print(f"{len(rows)} elevators with alternate-service text; {flagged} flagged for author review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
