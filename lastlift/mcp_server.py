"""The MCP server: the same fixed tools as the HTTP API, built from one registry.

Every tool is read-only on the live state (what-if runs on a throwaway copy; draft_action never files
anything), so all are annotated readOnlyHint. Each result envelope is stamped `via: "mcp"` and counted:
the agent reaches the tools only through this server (in-memory client), and a test checks that.
"""
import functools
import inspect
from collections import Counter

from fastmcp import FastMCP

from . import tools

INSTRUCTIONS = (
    "LastLift answers questions about step-free (lift) access at Boston's MBTA stations from a graph of the "
    "published station layouts. Results describe the open-data model and may differ from conditions on site. "
    "Never invent station, lift or platform ids: use resolve_place first. Always check mbta.com/alerts/access."
)
CALLS: Counter = Counter()          # tool name -> calls served through MCP (read by tests and the trace)


def _via_mcp(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        CALLS[fn.__name__] += 1
        result = fn(*args, **kwargs)
        return {**result, "via": "mcp"}
    wrapper.__signature__ = inspect.signature(fn)
    return wrapper


def build() -> FastMCP:
    mcp = FastMCP("lastlift", instructions=INSTRUCTIONS)
    for name, fn in tools.REGISTRY.items():
        mcp.tool(_via_mcp(fn), name=name, description=inspect.getdoc(fn),
                 annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
                              "openWorldHint": False})
    return mcp


mcp = build()
