"""Keep README.md and docs/*.md bound to the data: every number comes from claims.json, every table from the code.

    python scripts/readme_sync.py           # rewrite the generated parts of README.md and docs/*.md
    python scripts/readme_sync.py --check   # exit 1 if any of them is out of date (CI)

  <!--claim:KEY-->value<!--/claim-->           value = claims.json[KEY]
  <!--generated:cypher-->...<!--/generated-->  every Q_* statement in lastlift/queries.py
  <!--generated:counts-->...<!--/generated-->  graph counts from the snapshot MANIFEST
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lastlift import queries  # noqa: E402

README = ROOT / "README.md"
CLAIM = re.compile(r"<!--claim:([a-z0-9_]+)-->(.*?)<!--/claim-->", re.DOTALL)
GEN = re.compile(r"(<!--generated:([a-z]+)-->)(.*?)(<!--/generated-->)", re.DOTALL)


# Coefficients and scores that are not shares: printed as plain numbers, never as percentages.
PLAIN = ("spearman", "brier_skill", "_p10")


def fmt(v, key=""):
    if isinstance(v, float):
        if any(p in key for p in PLAIN):
            return f"{v:g}"
        return f"{v:.0%}" if 0 < v < 1 else f"{v:g}"
    if isinstance(v, list):
        return ", ".join(fmt(x) for x in v) or "none"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def cypher_table():
    rows = ["| Query | Cypher |", "|---|---|"]
    for name in sorted(n for n in dir(queries) if n.startswith("Q_")):
        text = " ".join(getattr(queries, name).split()).replace("|", "\\|")
        rows.append(f"| `{name}` | `{text}` |")
    return "\n".join(rows)


def counts_table():
    snap = sorted(p for p in (ROOT / "data" / "snapshots").iterdir() if (p / "MANIFEST.json").is_file())[-1]
    m = json.loads((snap / "MANIFEST.json").read_text(encoding="utf-8"))
    c = m["counts"]
    rows = ["| Node labels | Count |", "|---|---|"]
    rows += [f"| `{k.replace(',', ':')}` | {v:,} |" for k, v in sorted(c["nodes_by_labels"].items())]
    rows += ["", "| Relationship | Count |", "|---|---|"]
    rows += [f"| `{k}` | {v:,} |" for k, v in sorted(c["edges_by_type"].items())]
    rows += ["", "| Step-free (`SF`) edge kind | Count |", "|---|---|"]
    rows += [f"| `{k}` | {v:,} |" for k, v in sorted(c["sf_edges_by_kind"].items())]
    rows += ["", f"Snapshot `{snap.name}`, GTFS feed \"{m['feed_version']}\", seed sha256 `{m['seed_sha256'][:12]}…`: "
                 f"{c['nodes']:,} nodes, {c['edges']:,} relationships."]
    return "\n".join(rows)


def eval_table():
    path = ROOT / "eval" / "results" / "latest.json"
    if not path.is_file():
        return "_No evaluation run yet._"
    systems = json.loads(path.read_text(encoding="utf-8"))["systems"]
    order = [s for s in ("full_gemini", "llm_only_gemini", "router", "full_run2", "fallback_run2",
                         "full_run1_rate_limited", "fallback_run1_rate_limited") if s in systems]
    names = {"full_gemini": "Run 3: full agent (MCP tools + grounding), gemini-3.1-flash-lite",
             "llm_only_gemini": "Run 3: same model, no graph (FalkorDB off)",
             "router": "Router + templates (no LLM)",
             "full_run2": "Run 2: full agent (qwen at its daily cap; see amendment 2)",
             "fallback_run2": "Run 2: fallback subset, 12 q",
             "full_run1_rate_limited": "Run 1: full agent (rate-limited; amendment 1)",
             "fallback_run1_rate_limited": "Run 1: fallback subset (rate-limited)"}

    def cell(s, k):
        v = s.get(k)
        if v is None:
            return "–"
        if isinstance(v, dict):
            return f"{v['x']}/{v['n']}" if v.get("n") else "–"
        return str(v)
    head = ["System", "Right tools", "Gold ids", "Verdicts", "False accessible", "Abstains when it must",
            "Forbidden claims", "Template fallback", "Models"]
    rows = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for s in order:
        x = systems[s]
        rows.append("| " + " | ".join([names.get(s, s), cell(x, "tool_set"), cell(x, "ids"), cell(x, "verdicts"),
                                      cell(x, "false_accessible"), cell(x, "abstain_must"),
                                      cell(x, "forbidden_claims"), cell(x, "fallback_to_template"),
                                      ", ".join(x.get("models", [])) or "–"]) + " |")
    return "\n".join(rows)


def render(text):
    claims = json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))
    missing = [k for k in CLAIM.findall(text) if k[0] not in claims]
    if missing:
        raise SystemExit(f"a document cites claims that do not exist: {sorted({k[0] for k in missing})}")
    text = CLAIM.sub(lambda m: f"<!--claim:{m.group(1)}-->{fmt(claims[m.group(1)], m.group(1))}<!--/claim-->", text)
    gens = {"cypher": cypher_table, "counts": counts_table, "eval": eval_table}
    return GEN.sub(lambda m: f"{m.group(1)}\n{gens[m.group(2)]()}\n{m.group(4)}", text)


def main():
    files = [README] + sorted((ROOT / "docs").glob("*.md"))
    stale = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if "<!--claim:" not in text and "<!--generated:" not in text:
            continue
        new = render(text)
        if new == text:
            continue
        if "--check" in sys.argv:
            stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.write_text(new, encoding="utf-8", newline="\n")
            print(f"{path.relative_to(ROOT).as_posix()} synced")
    if "--check" in sys.argv:
        if stale:
            print(f"out of date: {', '.join(stale)}: run python scripts/readme_sync.py")
            return 1
        print("README.md and docs match claims.json and the code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
