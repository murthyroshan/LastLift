"""The pre-registered agent evaluation (eval/protocol.md, eval/gold_questions.yaml).

    python eval/run.py --system router          # no LLM; reproduces byte for byte
    python eval/run.py --system full            # Groq qwen + MCP tools + grounding (as shipped)
    python eval/run.py --system llm_only        # same model, alert headers + station list, NO tools (FalkorDB off)
    python eval/run.py --system fallback        # openai/gpt-oss-120b on the seeded 12-question subset
    python eval/run.py --summary                # combine the system files into eval/results/latest.json

Scoring is deterministic and the same for every system:
  tool-set      every required tool called and no forbidden tool (systems with tools only);
  ids           every gold id appears in the shipped answer or in the tool results it cites;
  verdicts      for each gold (platform, direction, verdict): the answer text carries the verdict's words
                (lost: lose/lost/no step-free...; single: only/single/one lift...); ok/cannot_assess as stated;
  false-accessible  a gold "lost" platform-direction whose answer carries no loss wording (headline safety metric);
  abstention    must-abstain rows abstain (cannot assess / not in the model / no data); other rows do not;
  forbidden     forbidden_claims substrings in the answer (case-insensitive);
  grounding     raw LLM answers that failed the grounding validator (before fallback) and shipped answers that fail it;
  MCP equality  every tool result through MCP has the same digest as the same call made directly.
Every proportion has a Wilson 95% interval.
"""
import argparse
import asyncio
import json
import random
import re
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift import alerts, tools  # noqa: E402
from lastlift.agent import grounding, llm, loop, replay  # noqa: E402
from lastlift.cuts import wilson  # noqa: E402

OUT = ROOT / "eval" / "results"
GOLD = yaml.safe_load((ROOT / "eval" / "gold_questions.yaml").read_text(encoding="utf-8"))
SAMPLING = json.loads((ROOT / "eval" / "sampling.json").read_text(encoding="utf-8"))
PACE_S = 30                                      # at most 2 questions a minute for the LLM systems
TPM_LIMIT = 8000                                 # provider tokens-per-minute limit (x-ratelimit-limit-tokens)
LOSS = re.compile(r"\b(lose|loses|lost|losing|no step-free|not step-free|cannot (reach|get)|can't (reach|get)|"
                  r"cut off|no route|unavailable)\b", re.I)
SINGLE = re.compile(r"\b(only|single|one lift|last lift|sole|alone)\b", re.I)
ABSTAIN = re.compile(r"((?<!\d )cannot assess|can't assess|not in the step-free model|no published station layout|"
                     r"not (a )?modelled|no data|i can only answer|unknown station|isn't in|is not in|"
                     r"could not find|couldn't find|no station)", re.I)
LLM_ONLY_SYSTEM = (
    "You are an assistant answering questions about step-free (lift) access at Boston's MBTA stations. You have no "
    "tools and no station layouts: only today's elevator alerts and the list of station names below. Answer in at "
    "most 5 short sentences. Never say 'safe'. If you cannot tell from this information, say you cannot assess."
)


def ids_found(gold_ids, answer, results):
    blob = answer + " " + " ".join(" ".join(r.get("entities", [])) + " " + (r.get("summary") or "") for r in results)
    return all(re.search(rf"(?<![\w-]){re.escape(g)}(?![\w-])", blob) for g in gold_ids)


def verdict_ok(v, answer):
    if v["verdict"] == "lost":
        return bool(LOSS.search(answer))
    if v["verdict"] == "single":
        return bool(SINGLE.search(answer))
    if v["verdict"] == "cannot_assess":
        return bool(ABSTAIN.search(answer))
    return not LOSS.search(answer)


def score(q, answer, results, called, system):
    row = {"id": q["id"], "category": q["category"]}
    if system != "llm_only":
        req, forb = set(q.get("required_tools", [])), set(q.get("forbidden_tools", []))
        row["tools_ok"] = req <= set(called) and not (forb & set(called))
    row["ids_ok"] = ids_found(q.get("gold_ids", []), answer, results) if q.get("gold_ids") else None
    vs = q.get("gold_verdicts", [])
    row["verdicts"] = [verdict_ok(v, answer) for v in vs]
    row["false_accessible"] = sum(1 for v in vs if v["verdict"] == "lost" and not LOSS.search(answer))
    abstained = bool(ABSTAIN.search(answer))
    row["abstain_ok"] = abstained if q.get("must_abstain") else not abstained
    row["forbidden"] = [c for c in q.get("forbidden_claims", []) if c.lower() in answer.lower()]
    return row


def llm_only_context():
    lines = ["Elevator alerts today:"]
    for c in alerts.closures_for("demo"):
        lines.append(f"- {c.get('header')}")
    names = sorted({s["name"] for s in json.loads((ROOT / "web" / "public" / "m" / "stations.json")
                                                   .read_text(encoding="utf-8"))})
    lines.append("Stations: " + ", ".join(names))
    return "\n".join(lines)


async def run_one(q, system, ctx):
    started = time.perf_counter()
    if system == "llm_only":
        chain = llm.Chain()
        chain.tiers = chain.tiers[:1]
        msg = await asyncio.to_thread(llm.chat, [{"role": "system", "content": LLM_ONLY_SYSTEM + "\n\n" + ctx},
                                                 {"role": "user", "content": q["question"]}], None, "auto", chain)
        answer = (msg.get("content") or "").strip()
        return {"answer": answer, "source": "llm", "results": [], "called": [], "events": [],
                "ms": round((time.perf_counter() - started) * 1000), "model": msg.get("model"),
                "tokens": msg.get("usage"), "raw_grounding_failed": None}
    r = await loop.ask(q["question"], scope="demo", mode="off" if system == "router" else "live")
    ev = r["events"]
    ans = next(e for e in ev if e["type"] == "answer")
    g = [e for e in ev if e["type"] == "grounding"]
    return {"answer": r["answer"], "source": r["source"], "results": r["results"],
            "called": [e["tool"] for e in ev if e["type"] == "tool_call"], "events": ev,
            "ms": round((time.perf_counter() - started) * 1000), "model": ans.get("model"), "tokens": ans.get("usage"),
            "raw_grounding_failed": (not g[0]["ok"]) if g else None,
            "failovers": [e for e in ev if e["type"] == "error" and e.get("stage") == "llm_failover"]}


def mcp_equal(events):
    """Every tool result through MCP equals the same call made directly (digest, which ignores timings)."""
    calls = [e for e in events if e["type"] == "tool_call"]
    res = [e for e in events if e["type"] == "tool_result"]
    ok = 0
    for c, r in zip(calls, res):
        fn = tools.REGISTRY[c["tool"]]
        args = dict(c["args"])
        if "scope" in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
            args["scope"] = "demo"
        ok += replay.digest(fn(**args)) == r["digest"]
    return ok, len(calls)


def prop(x, n):
    lo, hi = wilson(x, n) if n else (0, 0)
    return {"x": x, "n": n, "rate": round(x / n, 3) if n else None, "wilson95": [round(lo, 3), round(hi, 3)]}


def run(system):
    qs = GOLD["questions"]
    if system == "fallback":
        rng = random.Random(SAMPLING["agent_eval_fallback_subset"]["seed"])
        keep = set(rng.sample([q["id"] for q in qs], SAMPLING["agent_eval_fallback_subset"]["questions"]))
        qs = [q for q in qs if q["id"] in keep]
        base_tiers = llm.tiers
        llm.tiers = lambda: base_tiers()[1:]        # start the chain at gpt-oss-120b
    if system in ("full", "fallback", "llm_only"):
        llm.RETRY_WAIT_S = 60                       # wait out a per-minute token limit instead of failing over
        loop._llm_calls_today["n"] = 0
    ctx = llm_only_context() if system == "llm_only" else None
    tools.prepare_scope("demo")
    rows = []
    for i, q in enumerate(qs):
        t0 = time.time()
        out = asyncio.run(run_one(q, system, ctx))
        row = score(q, out["answer"], out["results"], out["called"], system)
        eq = mcp_equal(out["events"]) if out["events"] else (0, 0)
        row.update(answer=out["answer"], source=out["source"], tools=out["called"], mcp_equal=list(eq))
        if system != "router":
            row.update(ms=out["ms"], model=out["model"], tokens=out["tokens"],
                       raw_grounding_failed=out["raw_grounding_failed"],
                       shipped_ungrounded=bool(out["results"]) and out["source"] == "llm"
                       and bool(grounding.check(out["answer"], out["results"])),
                       failovers=len(out.get("failovers") or []))
        rows.append(row)
        print(f"{system} {q['id']}: tools={row.get('tools_ok')} ids={row['ids_ok']} src={out['source']}", flush=True)
        if system != "router" and i < len(qs) - 1:
            # pace from the provider's limits: at most 2 questions a minute, and never more tokens in a minute than
            # the model's tokens-per-minute limit (Groq: 8,000 for both chat models used here)
            used = sum((out.get("tokens") or {}).get(k) or 0 for k in ("input_tokens", "output_tokens"))
            wait = max(PACE_S, 60 * used / TPM_LIMIT + 5)
            time.sleep(max(0, wait - (time.time() - t0)))
    summary = summarise(rows, system)
    doc = {"system": system, "date": date.today().isoformat() if system != "router" else None,
           "questions": len(rows), "summary": summary, "rows": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{system}.json"
    path.write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8",
                    newline="\n")
    print(json.dumps(summary, indent=1))
    return 0


def summarise(rows, system):
    s = {}
    t = [r["tools_ok"] for r in rows if "tools_ok" in r]
    if t:
        s["tool_set"] = prop(sum(t), len(t))
    ids = [r["ids_ok"] for r in rows if r["ids_ok"] is not None]
    s["ids"] = prop(sum(ids), len(ids))
    v = [x for r in rows for x in r["verdicts"]]
    s["verdicts"] = prop(sum(v), len(v))
    s["false_accessible"] = sum(r["false_accessible"] for r in rows)
    ab = [r["abstain_ok"] for r in rows if r["category"] == "must_abstain"]
    s["abstain_must"] = prop(sum(ab), len(ab))
    other = [r["abstain_ok"] for r in rows if r["category"] != "must_abstain"]
    s["no_needless_abstain"] = prop(sum(other), len(other))
    s["forbidden_claims"] = sum(len(r["forbidden"]) for r in rows)
    eq = [r["mcp_equal"] for r in rows if r["mcp_equal"][1]]
    if eq:
        s["mcp_equal"] = prop(sum(a for a, _ in eq), sum(b for _, b in eq))
    if system != "router":
        llm_rows = [r for r in rows if r.get("raw_grounding_failed") is not None]
        s["raw_ungrounded"] = prop(sum(r["raw_grounding_failed"] for r in llm_rows), len(llm_rows))
        s["shipped_ungrounded"] = sum(r["shipped_ungrounded"] for r in rows)
        s["fallback_to_template"] = prop(sum(r["source"] == "template" for r in rows), len(rows))
        s["failovers"] = sum(r.get("failovers", 0) for r in rows)
        ms = sorted(r["ms"] for r in rows)
        s["latency_ms"] = {"p50": ms[len(ms) // 2], "p95": ms[min(len(ms) - 1, int(0.95 * len(ms)))]}
        tok = [r["tokens"] for r in rows if r.get("tokens")]
        if tok:
            s["tokens_per_question"] = {"in": round(statistics.mean(t.get("input_tokens") or 0 for t in tok)),
                                        "out": round(statistics.mean(t.get("output_tokens") or 0 for t in tok))}
        s["models"] = sorted({r["model"] for r in rows if r.get("model")})
    return s


def combine():
    docs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(OUT.glob("*.json")) if p.stem != "latest"}
    latest = {name: {"date": d["date"], "questions": d["questions"], **d["summary"]} for name, d in docs.items()}
    (OUT / "latest.json").write_text(json.dumps(latest, indent=1, sort_keys=True) + "\n", encoding="utf-8",
                                     newline="\n")
    print(json.dumps(latest, indent=1))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", choices=["router", "full", "llm_only", "fallback"])
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    sys.exit(combine() if a.summary else run(a.system))
