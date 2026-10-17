"""M13 A9: the MCP surface (golden lists of tools, resources, templates and prompts), output schemas, and the
operations server's approvals: elicitation when the client supports it, the website's link when it does not."""
import asyncio
import json
from pathlib import Path

import pytest
from fastmcp import Client

from lastlift import db
from lastlift.agents import roles
from lastlift.mcp_server import build_ops, mcp

GOLDEN = Path(__file__).parent / "golden" / "mcp_surface.json"


def surface():
    async def go():
        async with Client(mcp) as c:
            tools = await c.list_tools()
            return {"tools": [t.name for t in tools],
                    "resources": sorted(str(r.uri) for r in await c.list_resources()),
                    "templates": sorted(t.uri_template for t in await c.list_resource_templates()),
                    "prompts": sorted(p.name for p in await c.list_prompts()),
                    "all_read_only": all(t.annotations.read_only_hint for t in tools),
                    "all_have_output_schema": all(bool(t.output_schema) for t in tools)}
    return asyncio.run(go())


def test_public_surface_matches_the_golden_snapshot():
    got = surface()
    assert got["all_read_only"] and got["all_have_output_schema"]
    assert got == json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.skipif(not db.ping(), reason="FalkorDB not reachable")
def test_ops_approval_by_elicitation_or_by_link():
    from lastlift import state
    db.client().select_graph(state.graph_name("demo")).query(
        "MATCH (n) WHERE n:Assessment OR n:ActionProposal DETACH DELETE n")
    asyncio.run(roles.tick("demo"))
    props = roles.proposals("demo", "proposed")
    assert len(props) >= 2
    ops = build_ops("test-token")

    async def approve_via_elicitation(pid):
        async def handler(message, response_type, params, context):
            return {"decision": "approve"}
        async with Client(ops, elicitation_handler=handler) as c:
            return (await c.call_tool("approve_proposal", {"proposal_id": pid})).structured_content

    async def no_elicitation(pid):
        async with Client(ops) as c:
            return (await c.call_tool("approve_proposal", {"proposal_id": pid})).structured_content

    a = asyncio.run(approve_via_elicitation(props[0]["pid"]))
    assert a["status"] in ("approved_draft", "executed")
    b = asyncio.run(no_elicitation(props[1]["pid"]))
    assert b["status"] == "awaiting_approval" and b["approval_url"].endswith(props[1]["pid"])
    decided = {p["pid"]: p for p in roles.proposals("demo")}
    assert decided[props[0]["pid"]]["approved_via"] == f"mcp-elicit:{props[0]['pid']}"
