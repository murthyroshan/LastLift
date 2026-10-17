"""Recorded agent runs ("replays") and their verification.

A replay stores every event of one run. Each tool_result carries a digest of the tool's result with the
volatile parts removed (timings, what-if copy names, the via stamp). Verifying a replay re-executes every
recorded tool call through the MCP server on the same scope and compares digests: no drift = the graph
still gives exactly the recorded answers. The LLM's wording is not re-run; only the facts it was given.

Every replay is also hash-chained: chain[i] = sha256(chain[i-1] + canonical JSON of event i), and `head` is the last
link. Editing any byte of any event breaks the chain from that event on. The canonical JSON (sorted keys, no spaces,
integral floats written as integers) is the one a browser's JSON.stringify produces, so the website can check a
replay itself ("Verify this replay").
"""
import hashlib
import json
from pathlib import Path

from fastmcp import Client

from ..config import REPO_ROOT

REPLAY_DIR = REPO_ROOT / "web" / "public" / "replay"
# Not facts: timings, the via stamp, what-if copy names and graph names (which carry the deployment's
# GRAPH_PREFIX: dev_ll_ locally, ci_ll_ in CI). Everything else must match exactly.
VOLATILE = {"ms", "t_ms", "via", "copy", "graph"}


def canonical(x):
    if isinstance(x, dict):
        return {k: canonical(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [canonical(v) for v in x]
    return x


def digest(env: dict) -> str:
    return hashlib.sha256(json.dumps(canonical(env), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def jscanon(x) -> str:
    """Canonical JSON, identical to the website's canon() (web/src/components/AgentDrawer.tsx)."""
    def norm(v):
        if isinstance(v, dict):
            return {k: norm(v[k]) for k in sorted(v)}
        if isinstance(v, list):
            return [norm(i) for i in v]
        if isinstance(v, float) and v.is_integer():
            return int(v)
        return v
    return json.dumps(norm(x), separators=(",", ":"), ensure_ascii=False)


def chain(events) -> list[str]:
    h, out = "", []
    for e in events:
        h = hashlib.sha256((h + jscanon(e)).encode("utf-8")).hexdigest()
        out.append(h)
    return out


def seal(rec: dict) -> dict:
    rec["chain"] = chain(rec["events"])
    rec["head"] = rec["chain"][-1] if rec["chain"] else ""
    return rec


def chain_problems(rec: dict) -> list[str]:
    """Empty when the replay's events still hash to its recorded chain."""
    got = chain(rec.get("events", []))
    want = rec.get("chain") or []
    if not want:
        return [f"{rec.get('id')}: not sealed (no hash chain)"]
    for i, (a, b) in enumerate(zip(got, want)):
        if a != b:
            return [f"{rec.get('id')}: hash chain broken at event {i + 1}"]
    if len(got) != len(want) or rec.get("head") != (want[-1] if want else ""):
        return [f"{rec.get('id')}: hash chain length or head does not match"]
    return []


def load(replay_id: str) -> dict:
    return json.loads((REPLAY_DIR / f"{replay_id}.json").read_text(encoding="utf-8"))


async def verify(rec: dict, mcp) -> list[str]:
    """Check the hash chain, then re-execute the tool calls; return the list of drifts (empty = verified)."""
    broken = chain_problems(rec)
    if broken:
        return broken
    scope = next(e["scope"] for e in rec["events"] if e["type"] == "start")
    calls = [e for e in rec["events"] if e["type"] == "tool_call"]
    results = [e for e in rec["events"] if e["type"] == "tool_result"]
    drifts = []
    async with Client(mcp) as client:
        params = {t.name: set((t.input_schema or {}).get("properties", {})) for t in await client.list_tools()}
        for call, res in zip(calls, results):
            args = dict(call["args"])
            if "scope" in params.get(call["tool"], ()):
                args["scope"] = scope
            env = (await client.call_tool(call["tool"], args, raise_on_error=False)).structured_content or {}
            if digest(env) != res["digest"]:
                drifts.append(f"{rec['id']}: {call['tool']}({call['args']}) digest {digest(env)} != recorded {res['digest']}")
    return drifts
