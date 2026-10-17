"""Recorded agent runs ("replays") and their verification.

A replay stores every event of one run. Each tool_result carries a digest of the tool's result with the
volatile parts removed (timings, what-if copy names, the via stamp). Verifying a replay re-executes every
recorded tool call through the MCP server on the same scope and compares digests: no drift = the graph
still gives exactly the recorded answers. The LLM's wording is not re-run; only the facts it was given.
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


def load(replay_id: str) -> dict:
    return json.loads((REPLAY_DIR / f"{replay_id}.json").read_text(encoding="utf-8"))


async def verify(rec: dict, mcp) -> list[str]:
    """Re-execute a replay's tool calls; return the list of drifts (empty = verified)."""
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
