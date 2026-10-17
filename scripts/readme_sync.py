"""Keep README.md bound to the data: every number comes from claims.json, every table from the code.

    python scripts/readme_sync.py           # rewrite the generated parts of README.md
    python scripts/readme_sync.py --check   # exit 1 if README.md is out of date (CI)

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


def render(text):
    claims = json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))
    missing = [k for k in CLAIM.findall(text) if k[0] not in claims]
    if missing:
        raise SystemExit(f"README cites claims that do not exist: {sorted({k[0] for k in missing})}")
    text = CLAIM.sub(lambda m: f"<!--claim:{m.group(1)}-->{fmt(claims[m.group(1)], m.group(1))}<!--/claim-->", text)
    gens = {"cypher": cypher_table, "counts": counts_table}
    return GEN.sub(lambda m: f"{m.group(1)}\n{gens[m.group(2)]()}\n{m.group(4)}", text)


def main():
    text = README.read_text(encoding="utf-8")
    new = render(text)
    if "--check" in sys.argv:
        if new != text:
            print("README.md is out of date: run python scripts/readme_sync.py")
            return 1
        print("README.md matches claims.json and the code")
        return 0
    README.write_text(new, encoding="utf-8", newline="\n")
    print("README.md synced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
