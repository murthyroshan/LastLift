"""Score LastLift's per-alert verdicts against the author's blind gold labels.

    python scripts/eval.py            # writes validation/eval_live.csv and the live_* keys of claims.json

Key: validation/gold_live_author.csv (labelled by the author from MBTA's alert text only, committed
before any model output for these alerts existed). The AI-assistant labels in gold_live.csv are not
the key; they are only used to report labeller agreement (Cohen's kappa).

Model: lastlift.verdict.assess(), run for each alert alone on a what-if copy of the base graph.

Match rules (fixed in this file; decision D11):
  * gold CANNOT_ASSESS / OUT_OF_SCOPE and model CANNOT_ASSESS ........ ABSTAIN_OK
  * gold CANNOT_ASSESS / OUT_OF_SCOPE and model gives a verdict ....... GOLD_ABSTAINS (not scored)
  * gold gives a verdict and model CANNOT_ASSESS ....................... MODEL_ABSTAINS (not scored;
                                                                         counted in the unknown rate)
  * both give a verdict:
      same verdict, and no stated direction contradicts ............... AGREE
      same verdict but a stated direction contradicts .................. PARTIAL
      NO_LOSS vs ENTRANCE_ONLY (platforms reachable either way) ........ PARTIAL
      LOSS vs not-LOSS, but a stated direction agrees .................. PARTIAL
      otherwise ........................................................ DISAGREE
  A direction is "stated lost" when MBTA's class for it is RIDE_AND_RETURN, OTHER_STATION,
  SHUTTLE_OR_BUS or CROSS_THROUGH_TRAIN, "stated in-station" when it is IN_STATION; NOT_STATED is
  never compared.

Safety metric: false_accessible = alert-directions MBTA states as lost (a class above) where the
model says step-free access remains. Reported with every case listed, whatever the value.
"""
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift import verdict  # noqa: E402
from lastlift.wording import DISCLAIMERS  # noqa: E402

KEY = ROOT / "validation" / "gold_live_author.csv"
AI_LABELS = ROOT / "validation" / "gold_live.csv"
OUT = ROOT / "validation" / "eval_live.csv"
REPORT = ROOT / "validation" / "EVALUATION.md"
STATIC_PREFILL = ROOT / "validation" / "static_prefill.csv"
STATIC_MODEL = ROOT / "validation" / "static_model.csv"
STATIC_GOLD = ROOT / "validation" / "gold_static.csv"
LOST_CLASSES = {"RIDE_AND_RETURN", "OTHER_STATION", "SHUTTLE_OR_BUS", "CROSS_THROUGH_TRAIN"}
ABSTAIN = {"CANNOT_ASSESS", "OUT_OF_SCOPE"}
REACHABLE = {"NO_LOSS", "ENTRANCE_ONLY"}


def wilson(k, n, z=1.959964):
    if n == 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((c - h) / d, 3), round((c + h) / d, 3)


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[c] * cb[c] for c in set(a) | set(b)) / (n * n)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def stated(row):
    out = {}
    for d in ("board", "exit"):
        c = row[f"mbta_{d}_class"]
        if c in LOST_CLASSES:
            out[d] = "lost"
        elif c == "IN_STATION":
            out[d] = "ok"
    return out


def match(gold, model):
    gv, mv = gold["exp_verdict"], model["verdict"]
    if gv in ABSTAIN:
        return "ABSTAIN_OK" if mv in ABSTAIN else "GOLD_ABSTAINS"
    if mv in ABSTAIN:
        return "MODEL_ABSTAINS"
    lost = {d for d in ("board", "exit") if model["lost"].get(d)}
    dirs = stated(gold)
    contradicts = [d for d, s in dirs.items() if (s == "lost") != (d in lost)]
    agrees = [d for d, s in dirs.items() if (s == "lost") == (d in lost)]
    if gv == mv:
        return "PARTIAL" if contradicts else "AGREE"
    if {gv, mv} <= REACHABLE:
        return "PARTIAL"
    if "LOSS" in (gv, mv) and agrees:
        return "PARTIAL"
    return "DISAGREE"


def main():
    gold = list(csv.DictReader(KEY.open(encoding="utf-8-sig")))
    rows, false_acc, false_inacc = [], [], []
    named_total = named_found = 0
    type_n = type_agree = 0
    for g in gold:
        m = verdict.assess(g["facility_ids"].split(";"))
        reroute_lifts = sorted({f for p in m["platforms"] for d in ("board", "exit")
                                for f in ((p[d].get("reroute") or {}).get("lifts") or [])})
        m_lifts = sorted(set(m["alt_lifts"]) | set(reroute_lifts))
        verdict_match = match(g, m)
        if m["verdict"] not in ABSTAIN and g["exp_verdict"] not in ABSTAIN:
            for d, s in stated(g).items():
                model_lost = bool(m["lost"].get(d))
                if s == "lost" and not model_lost:
                    false_acc.append(f"{g['gold_id']} {d}")
                if s == "ok" and model_lost:
                    false_inacc.append(f"{g['gold_id']} {d}")
                gc, mc = g[f"mbta_{d}_class"], m["classes"].get(d)
                type_n += 1
                type_agree += (gc == mc) or (gc == "IN_STATION" and mc == "UNAFFECTED")
            named = [x for x in g["mbta_named_elevators"].split(";") if x]
            named_total += len(named)
            named_found += sum(1 for x in named if x in m_lifts)
        rows.append({**g, "model_verdict": m["verdict"],
                     "model_board_class": m["classes"].get("board", ""), "model_exit_class": m["classes"].get("exit", ""),
                     "model_lost_board": ";".join(m["lost"].get("board", [])),
                     "model_lost_exit": ";".join(m["lost"].get("exit", [])),
                     "model_entrances_cut": ";".join(m["entrances_cut"]),
                     "model_alt_lifts": ";".join(m_lifts), "model_modelled": ";".join(m["modelled"]),
                     "match": verdict_match})

    fields = list(gold[0].keys()) + ["model_verdict", "model_board_class", "model_exit_class", "model_lost_board",
                                     "model_lost_exit", "model_entrances_cut", "model_alt_lifts", "model_modelled", "match"]
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    c = Counter(r["match"] for r in rows)
    scored = c["AGREE"] + c["PARTIAL"] + c["DISAGREE"]
    ai = {r["gold_id"]: r["exp_verdict"] for r in csv.DictReader(AI_LABELS.open(encoding="utf-8-sig"))}
    ids = [g["gold_id"] for g in gold]
    live = {
        "live_key": "validation/gold_live_author.csv (author, blind, MBTA text only)",
        "live_closures": len(rows),
        "live_scored": scored,
        "live_agree": c["AGREE"], "live_partial": c["PARTIAL"], "live_disagree": c["DISAGREE"],
        "live_agree_wilson95": list(wilson(c["AGREE"], scored)),
        "live_agree_or_partial_wilson95": list(wilson(c["AGREE"] + c["PARTIAL"], scored)),
        "live_abstain_ok": c["ABSTAIN_OK"], "live_model_abstains": c["MODEL_ABSTAINS"],
        "live_gold_abstains": c["GOLD_ABSTAINS"],
        "live_unknown_rate": f"{sum(1 for r in rows if r['model_verdict'] in ABSTAIN)}/{len(rows)}",
        "live_false_accessible": len(false_acc), "live_false_accessible_cases": false_acc,
        "live_false_inaccessible": len(false_inacc), "live_false_inaccessible_cases": false_inacc,
        "live_named_lift_recall": f"{named_found}/{named_total}",
        "live_reroute_type_agree": f"{type_agree}/{type_n}",
        "live_labeller_kappa_author_vs_ai": kappa([g["exp_verdict"] for g in gold], [ai[i] for i in ids]),
        "live_labeller_raw_agreement_author_vs_ai": f"{sum(g['exp_verdict'] == ai[g['gold_id']] for g in gold)}/{len(gold)}",
    }
    static = static_sweep()
    claims_path = ROOT / "claims.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    claims = {k: v for k, v in claims.items() if not k.startswith(("live_", "static_"))}
    claims.update(live)
    claims.update(static)
    claims_path.write_text(json.dumps(claims, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    REPORT.write_text(report(rows, live, static), encoding="utf-8", newline="\n")

    for r in rows:
        print(f"{r['gold_id']} {r['facility_ids']:16} gold {r['exp_verdict']:13} model {r['model_verdict']:13} {r['match']}")
    print(json.dumps({**live, **static}, indent=1))
    return 0


# --- static sweep -----------------------------------------------------------------------------------
def static_sweep():
    """Score the static sweep from the author's labels only (validation/gold_static.csv). Until that file
    exists the sweep is reported as awaiting review, with no agreement figure."""
    if not STATIC_PREFILL.is_file() or not STATIC_MODEL.is_file():
        return {"static_sweep_status": "not run (scripts/static_sweep.py)"}
    pre = list(csv.DictReader(STATIC_PREFILL.open(encoding="utf-8")))
    flagged = sum(r["review_required"] == "Y" for r in pre)
    out = {"static_sweep_rows": len(pre), "static_sweep_flagged_for_review": flagged}
    if not STATIC_GOLD.is_file():
        out["static_sweep_status"] = f"awaiting author review ({flagged} of {len(pre)} rows flagged)"
        return out
    model = {r["facility_id"]: r for r in csv.DictReader(STATIC_MODEL.open(encoding="utf-8"))}
    lost = {"RIDE_AND_RETURN", "NO_ROUTE"}
    c = Counter()
    for g in csv.DictReader(STATIC_GOLD.open(encoding="utf-8-sig")):
        m = model.get(g["facility_id"])
        if m is None:
            continue
        gold = {"exp_verdict": g["author_verdict"], "mbta_board_class": g["author_board_class"],
                "mbta_exit_class": g["author_exit_class"]}
        mm = {"verdict": m["model_verdict"],
              "lost": {d: (["x"] if m[f"model_{d}_class"] in lost else []) for d in ("board", "exit")}}
        c[(g["labelled_by"].startswith("author"), match(gold, mm))] += 1
    for who, key in ((True, "reviewed"), (False, "prefill")):
        scored = sum(n for (a, mt), n in c.items() if a == who and mt in ("AGREE", "PARTIAL", "DISAGREE"))
        agree = c[(who, "AGREE")]
        out[f"static_{key}_scored"] = scored
        out[f"static_{key}_agree"] = agree
        out[f"static_{key}_partial"] = c[(who, "PARTIAL")]
        out[f"static_{key}_disagree"] = c[(who, "DISAGREE")]
        out[f"static_{key}_agree_wilson95"] = list(wilson(agree, scored))
    out["static_sweep_status"] = "scored from validation/gold_static.csv"
    return out


# --- report -----------------------------------------------------------------------------------------
def report(rows, live, static):
    """validation/EVALUATION.md, generated: every number comes from this run."""
    lo, hi = live["live_agree_wilson95"]
    lines = [
        "# Evaluation (generated by `scripts/eval.py`; do not edit by hand)", "",
        "> " + DISCLAIMERS["validation"], "",
        "## Live closures (14 MBTA lift alerts, frozen 15 Oct 2026)", "",
        f"Key: `{live['live_key']}`. Model: each alert's lifts closed alone on a copy of the base graph.", "",
        f"- **Scored by both:** {live['live_scored']}: {live['live_agree']} agree, {live['live_partial']} partial, "
        f"{live['live_disagree']} disagree. Agreement {live['live_agree']}/{live['live_scored']}, "
        f"Wilson 95% interval {lo:.0%}-{hi:.0%}.",
        f"- **False accessible** (MBTA says a direction is lost, the model says it is not): "
        f"{live['live_false_accessible']} ({', '.join(live['live_false_accessible_cases']) or 'none'}).",
        f"- **False inaccessible:** {live['live_false_inaccessible']} "
        f"({', '.join(live['live_false_inaccessible_cases']) or 'none'}).",
        f"- **Model abstains** (no station layout data): {live['live_model_abstains']}; both abstain: "
        f"{live['live_abstain_ok']}; unknown rate {live['live_unknown_rate']}.",
        f"- **Named-lift recall:** {live['live_named_lift_recall']}. **Reroute-type agreement:** "
        f"{live['live_reroute_type_agree']} stated directions.",
        f"- **Labeller agreement** (author vs AI-assistant labels, verdicts): "
        f"{live['live_labeller_raw_agreement_author_vs_ai']}, Cohen's kappa {live['live_labeller_kappa_author_vs_ai']}.",
        "", "| id | lift(s) | MBTA board / exit (author) | author verdict | model verdict | match |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['gold_id']} | {r['facility_ids'].replace(';', ', ')} | {r['mbta_board_class']} / "
                     f"{r['mbta_exit_class']} | {r['exp_verdict']} | {r['model_verdict']} | {r['match']} |")
    lines += ["", "### Every row that is not a plain agreement", ""]
    for r in rows:
        if r["match"] != "AGREE":
            extra = []
            if r["model_entrances_cut"]:
                extra.append(f"entrances cut in the model: {r['model_entrances_cut']}")
            if r["model_alt_lifts"]:
                extra.append(f"model's alternative lifts: {r['model_alt_lifts'].replace(';', ', ')}")
            lines.append(f"- **{r['gold_id']} ({r['facility_ids']}), {r['match']}.** Author: {r['exp_verdict']} "
                         f"({r['labeller_notes']}) Model: {r['model_verdict']}" + (f"; {'; '.join(extra)}." if extra else "."))
    lines += ["", "## Static sweep (MBTA elevator alternate-service text)", "",
              f"Status: {static.get('static_sweep_status')}.", ""]
    if "static_reviewed_scored" in static:
        lo2, hi2 = static["static_reviewed_agree_wilson95"]
        lines.append(f"- Author-reviewed rows: {static['static_reviewed_agree']}/{static['static_reviewed_scored']} agree "
                     f"(Wilson 95% {lo2:.0%}-{hi2:.0%}), {static['static_reviewed_partial']} partial, "
                     f"{static['static_reviewed_disagree']} disagree.")
        lines.append(f"- Rows labelled by the regex pre-fill and not reviewed: {static['static_prefill_scored']}. They "
                     f"were left unreviewed because they matched the model's verdict, so they are not evidence of "
                     f"agreement and are not counted in the figure above.")
    lines += ["", "Match rules, metrics and their definitions: the docstring of `scripts/eval.py`.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
