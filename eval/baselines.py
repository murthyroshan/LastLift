"""Graph versus no graph: the baselines pre-registered in eval/llm_baseline.md.

    python eval/baselines.py            # B-COUNT and B-BFS (no network); B-LLM from the cache, calling the model
                                        # only for prompts not cached yet. Writes eval/results/baselines.json

B-COUNT  rule "a platform depends on a single lift if its station has exactly one lift", against the certified
         max-flow result for every assessed lift-dependent platform.
B-BFS    analytic: how many reachability searches it takes to find every single point of failure (and every pair)
         without max-flow, next to LastLift's one max-flow per platform-direction.
B-LLM    gemini-3.1-flash-lite, temperature 0, reads a station's pathways.txt rows and stop names and answers the
         fixed question for one platform (leaving it: the exit direction). 30 platforms, stratified by station size
         (at most 50 pathway rows / 51-150), seed in eval/sampling.json. Scoring: k exact; cut set exact when it
         equals one of the certified minimum cuts (for k = 1 also the full set of single points of failure).
         The model answers in prose, so a separate extraction call (same model, temperature 0, cached) restates
         its own answer as JSON {k, ids}; ids are kept only if they are GTFS elevator facility ids. An answer
         whose extraction gives no k counts as wrong; provider errors (HTTP 503) are retried, never scored. Every prompt and raw answer is kept in eval/results/llm_baseline/.
"""
import csv
import hashlib
import io
import json
import random
import re
import sys
import time
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift.cuts import wilson  # noqa: E402
from lastlift.seed import latest_snapshot  # noqa: E402

OUT = ROOT / "eval" / "results"
CACHE = OUT / "llm_baseline"
QUESTION = ("A rider who needs step-free access is on platform {x}. How many elevators must fail before they can no "
            "longer leave the platform step-free, and which elevators are those? Answer with a number and a list of "
            "elevator ids.")


def prop(x, n):
    lo, hi = wilson(x, n) if n else (0, 0)
    return {"x": x, "n": n, "rate": round(x / n, 3) if n else None, "wilson95": [round(lo, 3), round(hi, 3)]}


def certified():
    snap = latest_snapshot()
    rows = [json.loads(x) for x in (snap / "precomputed.jsonl").read_text(encoding="utf-8").splitlines()]
    net = json.loads((snap / "network.json").read_text(encoding="utf-8"))
    nodes = [json.loads(x) for x in (snap / "nodes.jsonl").read_text(encoding="utf-8").splitlines()]
    lifts_at = defaultdict(set)
    for n in nodes:
        if "Lift" in n["labels"] and "Node" in n["labels"]:
            lifts_at[n["station_id"]].add(n["facility_id"])
    return rows, net, lifts_at


def b_count(rows, lifts_at):
    fp = fn = tp = tn = 0
    for r in rows:
        if r.get("status") or r.get("wheelchair_boarding") == 2:
            continue
        ks = [r.get(f"k_{d}") for d in ("board", "exit") if not r.get(f"at_grade_{d}")]
        if not ks or 0 in ks or None in ks:
            continue
        truth = min(ks) == 1
        rule = len(lifts_at[r["station_id"]]) == 1
        tp += truth and rule
        tn += not truth and not rule
        fp += rule and not truth
        fn += truth and not rule
    return {"platforms": tp + tn + fp + fn, "rule_wrong": fp + fn, "says_single_but_not": fp,
            "misses_single": fn, "agree": tp + tn}


def b_bfs(net):
    singles = pairs = 0
    for p in net["platform"].values():
        for d in ("board", "exit"):
            n = len(p[d].get("relevant") or [])
            if p[d].get("k"):
                singles += n
                pairs += n * (n - 1) // 2
    facs = len(net["lifts"])
    origins = len(net["stations"])
    return {"platform_single_searches": singles, "platform_pair_searches": pairs,
            "network_single_searches": facs * origins, "network_pair_searches": facs * (facs - 1) // 2 * origins,
            "lastlift_maxflow_calls": json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))["maxflow_calls"]}


def station_csv(z, station):
    stops = list(csv.DictReader(io.TextIOWrapper(z.open("stops.txt"), encoding="utf-8-sig")))
    mine = {s["stop_id"] for s in stops if s["stop_id"] == station or s.get("parent_station") == station}
    names = [s for s in stops if s["stop_id"] in mine]
    paths = [p for p in csv.DictReader(io.TextIOWrapper(z.open("pathways.txt"), encoding="utf-8-sig"))
             if p["from_stop_id"] in mine or p["to_stop_id"] in mine]
    return paths, names


def to_csv(rows, cols):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


EXTRACT = ("Below is an answer to the question: how many elevators must fail before a rider can no longer leave a "
           "platform step-free, and which elevators are those. Restate exactly what the answer concludes, without "
           "judging it. Reply with JSON only: {\"k\": <integer or null if the answer gives no number>, "
           "\"ids\": [<elevator ids the answer names as the ones that must fail, as strings>]}\n\nANSWER:\n")


def parse(llm, tier, rec, elevators):
    """(k, elevator ids) restated by the model from its own answer (cached in rec["extracted"])."""
    if "extracted" not in rec:
        for attempt in range(4):
            try:
                msg = llm.call_tier(tier, [{"role": "user", "content": EXTRACT + rec["answer"]}], max_tokens=200)
                rec["extracted"] = msg.get("content") or ""
                break
            except llm.LLMError:
                time.sleep(20 * (attempt + 1))
    m = re.search(r"\{.*\}", rec.get("extracted") or "", re.S)
    try:
        x = json.loads(m.group(0)) if m else {}
    except ValueError:
        x = {}
    k = x.get("k") if isinstance(x.get("k"), int) else None
    ids = {str(i) for i in x.get("ids") or [] if str(i) in elevators}
    return k, ids


def b_llm(net):
    from lastlift.agent import llm
    seed = json.loads((ROOT / "eval" / "sampling.json").read_text(encoding="utf-8"))["llm_baseline_platform_sample"]
    z = zipfile.ZipFile(ROOT / "data" / "raw" / "MBTA_GTFS.zip")
    by_station = defaultdict(list)
    for stop, p in net["platform"].items():
        if p["exit"].get("k") and not p["exit"].get("at_grade"):
            by_station[p["station_id"]].append(stop)
    sizes = {}
    for st in sorted(by_station):
        paths, _ = station_csv(z, st)
        sizes[st] = len(paths)
    strata = {"small": [], "medium": []}
    for st, stops in sorted(by_station.items()):
        n = sizes[st]
        if n <= seed["max_pathway_rows_per_station"]:
            strata["small" if n <= 50 else "medium"] += [(st, s) for s in sorted(stops)]
    rng = random.Random(seed["seed"])
    half = seed["rows"] // 2
    picks = rng.sample(strata["small"], min(half, len(strata["small"]))) + \
        rng.sample(strata["medium"], min(seed["rows"] - half, len(strata["medium"])))
    CACHE.mkdir(parents=True, exist_ok=True)
    tier = llm.tiers()[2]
    elevators = {f["facility_id"] for f in csv.DictReader(io.TextIOWrapper(z.open("facilities.txt"), encoding="utf-8-sig"))
                 if f["facility_type"] == "elevator"}
    rows = []
    for st, stop in picks:
        paths, names = station_csv(z, st)
        x = next((f"{n['stop_name']} ({n.get('platform_name') or ''}, stop_id {stop})" for n in names
                  if n["stop_id"] == stop), stop)
        prompt = ("pathways.txt rows for this station:\n" + to_csv(paths, list(paths[0].keys())) +
                  "\nstops.txt rows for this station:\n" +
                  to_csv(names, ["stop_id", "stop_name", "platform_name", "location_type", "parent_station",
                                 "wheelchair_boarding"]) + "\n" + QUESTION.format(x=x))
        key = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        path = CACHE / f"{stop}_{key}.json"
        if path.is_file():
            rec = json.loads(path.read_text(encoding="utf-8"))
        else:
            out, err = "", None
            for attempt in range(4):
                try:
                    msg = llm.call_tier(tier, [{"role": "user", "content": prompt}], max_tokens=3000)
                    out, err = msg.get("content") or "", None
                    break
                except llm.LLMError as exc:
                    err = str(exc)
                    time.sleep(20 * (attempt + 1))
            rec = {"station": st, "stop_id": stop, "model": tier.model, "prompt": prompt, "answer": out, "error": err}
            if not err:
                path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        truth = net["platform"][stop]["exit"]
        had = "extracted" in rec
        k_pred, ids = parse(llm, tier, rec, elevators)
        if not had and "extracted" in rec and not rec.get("error"):
            path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        cuts = [set(c) for c in truth.get("mincuts") or []]
        singles = {c[0] for c in truth.get("minimal") or [] if len(c) == 1}
        set_ok = bool(ids) and (ids in cuts or (truth["k"] == 1 and ids == singles))
        rows.append({"station": st, "stop_id": stop, "rows": sizes[st], "k": truth["k"], "k_pred": k_pred,
                     "k_ok": k_pred == truth["k"], "ids_pred": sorted(ids), "cut_ok": set_ok,
                     "error": rec.get("error")})
    return {"model": tier.model, "n": len(rows), "k_exact": prop(sum(r["k_ok"] for r in rows), len(rows)),
            "cut_exact": prop(sum(r["cut_ok"] for r in rows), len(rows)), "rows": rows}


def main():
    rows, net, lifts_at = certified()
    doc = {"b_count": b_count(rows, lifts_at), "b_bfs": b_bfs(net), "b_llm": b_llm(net)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "baselines.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8",
                                        newline="\n")
    print(json.dumps({k: v for k, v in doc.items() if k != "b_llm"}, indent=1))
    print(json.dumps({k: v for k, v in doc["b_llm"].items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
