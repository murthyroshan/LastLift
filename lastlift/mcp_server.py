"""The MCP servers, built from one tool registry.

  /mcp      public and read-only: the tools (every result stamped `via: "mcp"`, with an output schema), resources
            (the model, station dossiers and Mermaid drawings, lift dossiers, open incidents, recorded runs, the
            evaluation) and prompts (triage a closure, brief a station, plan a trip, explain a certificate).
  /mcp-ops  operations, only when OPS_MCP_TOKEN is set (bearer token): the same read tools plus the approvals
            inbox. approve_proposal asks the human through MCP elicitation when the client supports it, and
            otherwise returns the website's approval link; both paths write the same approved_via field.

Every public tool is read-only on the live state (what-if runs on a throwaway copy; draft_action never files
anything), so all are annotated readOnlyHint. The agent reaches the tools only through this server (in-memory
client), and a test checks that.
"""
import functools
import inspect
import json
import os
from collections import Counter

from fastmcp import Context, FastMCP

from . import tools
from .config import REPO_ROOT

INSTRUCTIONS = (
    "LastLift answers questions about step-free (lift) access at Boston's MBTA stations from a graph of the "
    "published station layouts. Results describe the open-data model and may differ from conditions on site. "
    "Never invent station, lift or platform ids: use resolve_place first. Always check mbta.com/alerts/access."
)
CALLS: Counter = Counter()          # tool name -> calls served through MCP (read by tests and the trace)
ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["ok", "tool", "summary", "data", "entities"],
    "properties": {
        "ok": {"type": "boolean"}, "tool": {"type": "string"},
        "summary": {"type": "string", "description": "one-line result in plain language"},
        "data": {"type": "object"}, "entities": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "object", "description": "Cypher query ids, graph, milliseconds"},
        "highlight": {"type": "object"}, "via": {"type": "string"},
    },
}
SITE = os.environ.get("PUBLIC_SITE", "https://lastlift.vercel.app")


def _via_mcp(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from fastmcp.exceptions import ToolError
        from redis.exceptions import RedisError
        CALLS[fn.__name__] += 1
        try:
            result = fn(*args, **kwargs)
        except RedisError as exc:           # never pass on a connection error's text: it names the server
            raise ToolError("graph server unavailable: LastLift gives no answer without the graph") from exc
        return {**result, "via": "mcp"}
    wrapper.__signature__ = inspect.signature(fn)
    return wrapper


def _add_tools(server):
    for name in sorted(tools.REGISTRY):
        fn = tools.REGISTRY[name]
        server.tool(_via_mcp(fn), name=name, description=inspect.getdoc(fn), output_schema=ENVELOPE_SCHEMA,
                    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
                                 "openWorldHint": False})


def _add_resources(server):
    @server.resource("lastlift://model", mime_type="application/json")
    def model() -> str:
        """The model: rules, snapshot, headline numbers and licence."""
        claims = json.loads((REPO_ROOT / "claims.json").read_text(encoding="utf-8")) \
            if (REPO_ROOT / "claims.json").is_file() else {}
        keep = ("snapshot_id", "seed_sha256", "feed_version", "platforms_step_free", "platforms_single_lift",
                "spof_lifts", "net_spof_lifts", "n2_critical_pairs")
        return json.dumps({"rules": "docs/model_rules.md", "claims": {k: claims.get(k) for k in keep},
                           "licence": "MBTA GTFS and V3 API under the MassDOT Developers License Agreement; "
                                      "unofficial, open-data model"})

    @server.resource("lastlift://stations/{station_id}", mime_type="application/json")
    def station(station_id: str) -> str:
        """Every platform's certified lift redundancy at a station (demo state)."""
        return json.dumps(tools.platform_redundancy(station_id, "demo"))

    @server.resource("lastlift://stations/{station_id}/graph.mmd", mime_type="text/plain")
    def station_graph(station_id: str) -> str:
        """The station's step-free graph as a Mermaid flowchart (closed lifts red, last lifts gold)."""
        from .agents import tickets
        return tickets.mermaid(station_id, "demo", "")

    @server.resource("lastlift://lifts/{facility_id}/dossier.md", mime_type="text/markdown")
    def dossier(facility_id: str) -> str:
        """A one-page brief on a lift (markdown)."""
        return (tools.lift_dossier(facility_id, "demo").get("data") or {}).get("markdown", "")

    @server.resource("lastlift://incidents/open", mime_type="application/json")
    def incidents() -> str:
        """The operations agents' current assessments (demo state)."""
        from .agents import roles
        return json.dumps([a for a in roles.incidents("demo") if a["current"]])

    @server.resource("lastlift://runs/{run_id}", mime_type="application/json")
    def run(run_id: str) -> str:
        """A recorded agent run with its hash chain (see 'Verify this replay')."""
        from .agent import replay
        return json.dumps(replay.load(run_id), ensure_ascii=False)

    @server.resource("lastlift://eval/latest", mime_type="application/json")
    def evaluation() -> str:
        """The pre-registered agent evaluation and the baselines."""
        p = REPO_ROOT / "data" / "eval" / "latest.json"
        return p.read_text(encoding="utf-8") if p.is_file() else "{}"


def _add_prompts(server):
    @server.prompt()
    def triage_closure(facility_id: str) -> str:
        """Assess a lift closure the way LastLift's Analyst does."""
        return (f"Lift {facility_id} is reported closed. Use resolve_place, then platform_redundancy for its station, "
                "network_impact with this lift, and step_free_route for any platform that loses step-free access. Say "
                "'cannot assess' if the lift is not modelled. End with: Check mbta.com/alerts/access.")

    @server.prompt()
    def station_briefing(station: str) -> str:
        """A short step-free briefing for one station."""
        return (f"Brief me on step-free access at {station}: resolve_place, platform_redundancy, then lift_dossier "
                "for any lift that is the only lift for a platform. Plain language, at most 6 sentences.")

    @server.prompt()
    def plan_step_free_trip(from_station: str, to_station: str) -> str:
        """Plan a step-free trip and name the lifts it depends on."""
        return (f"Plan a step-free trip from {from_station} to {to_station} with step_free_route, name every lift it "
                "uses and the backup if one of them is out. Check mbta.com/alerts/access.")

    @server.prompt()
    def explain_certificate(platform_id: str, direction: str) -> str:
        """Explain why a platform-direction has exactly k lift routes."""
        return (f"Explain the redundancy certificate for platform {platform_id} ({direction}): call "
                "platform_redundancy and lift_dossier, give k, the lift-disjoint routes, and every minimum cut, in "
                "plain words.")


def build() -> FastMCP:
    server = FastMCP("lastlift", instructions=INSTRUCTIONS)
    _add_tools(server)
    _add_resources(server)
    _add_prompts(server)
    return server


def build_ops(token: str) -> FastMCP:
    from fastmcp.server.auth import StaticTokenVerifier
    server = FastMCP("lastlift-ops", instructions=INSTRUCTIONS + " Operations: proposals need a human decision.",
                     auth=StaticTokenVerifier(tokens={token: {"client_id": "ops", "scopes": ["ops"]}}))
    _add_tools(server)

    @server.tool(annotations={"readOnlyHint": True})
    def list_proposals(status: str = "proposed", scope: str = "demo") -> dict:
        """The approvals inbox: action proposals awaiting a human decision."""
        from .agents import roles
        return {"proposals": roles.proposals(scope, status)}

    @server.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
    async def approve_proposal(proposal_id: str, ctx: Context, scope: str = "demo"):
        """Approve or reject a proposal. A client that supports elicitation is asked for the decision (an
        input-required round trip, MCP 2026-07-28); a client without elicitation gets the website's approval link.
        Approvals are idempotent per proposal."""
        import mcp.types as mt

        from .agents import roles
        try:
            can_elicit = bool(ctx.session.client_params.capabilities.elicitation)
        except Exception:
            can_elicit = False
        if not can_elicit:                      # hand the decision to the website's approvals inbox
            return {"status": "awaiting_approval", "approval_url": f"{SITE}/#/approvals?pid={proposal_id}"}
        answers = ctx.input_responses
        if answers is None:                     # first round: ask the human through the client
            schema = {"type": "object", "required": ["decision"],
                      "properties": {"decision": {"type": "string", "enum": ["approve", "reject"]},
                                     "note": {"type": "string"}}}
            return mt.InputRequiredResult(inputRequests={"decision": mt.ElicitRequest(params=mt.ElicitRequestFormParams(
                message=f"LastLift proposal {proposal_id}: approve or reject?", requestedSchema=schema))},
                requestState=proposal_id)
        res = answers.get("decision")
        if getattr(res, "action", "") != "accept" or not (res.content or {}).get("decision"):
            return {"status": "no_decision", "action": getattr(res, "action", "")}
        return roles.decide(scope, ctx.request_state or proposal_id, res.content["decision"],
                            f"mcp-elicit:{proposal_id}")

    return server


mcp = build()
