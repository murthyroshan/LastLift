"""The agent loop. Tools come only from the MCP server, through an in-memory MCP client (list_tools / call_tool);
the agent never imports or calls the tool registry itself.

  live:      the provider chain (llm.py: qwen -> gpt-oss-120b -> Gemini flash-lite) with parallel tool calls, at
             most MAX_ROUNDS tool rounds, then a final call with tool_choice "none" to write the answer; the answer
             must pass the grounding validator. Every tier switch is an "error" event with stage "llm_failover".
  otherwise: the rule-based router chooses the tools.
Any LLM failure, budget exhaustion or grounding failure falls back to the deterministic template over the
tool results already gathered (or the router's, if none were gathered). Every step is emitted as an event
(contracts/ask_events.schema.json): the SSE stream, the recorder and the tests all consume the same events.

Tracing follows W3C Trace Context: a caller's `traceparent` header joins its trace, otherwise a new trace id is
made; the run, each tool call and each LLM call get their own span ids, carried on the events.
"""
import asyncio
import json
import re
import secrets
import time

from fastmcp import Client

from ..config import settings
from ..mcp_server import mcp
from . import grounding, llm, replay, router, templates

MAX_ROUNDS = 3
EVENT_SCHEMA_VERSION = 1
SYSTEM = (
    "You are LastLift. You answer questions about step-free (lift) access at Boston's MBTA stations, using only "
    "the tools. Rules: call resolve_place first when the user names a station or lift; never invent station, "
    "lift or platform ids or numbers; every id and number you write must appear in a tool result. Say a "
    "platform 'loses step-free access in the open-data model', never 'stranded', 'safe' or a bare 'accessible'. "
    "If a tool says 'cannot assess', say so plainly. If a platform loses step-free access (now or in a what-if), "
    "call step_free_route with from_station and to_platform (boarding) or from_platform (exiting), plus also_closed "
    "for a what-if, to find the step-free alternative via other stations, and give it; only if that returns no "
    "route, say no step-free route exists in the open-data model. For effects across the network (journeys between "
    "stations, stations cut off, which lift is now the last link, critical lift pairs) call network_impact. "
    "Answer in at most 5 short sentences, plain language, and end with: "
    "Check mbta.com/alerts/access."
)
CLAIMS_PROMPT = (
    "Now write the answer as JSON only, no other text: {\"claims\": [{\"kind\": \"verdict|route|count|lift_role|"
    "caveat\", \"text\": \"one short sentence\", \"cites\": [step numbers]}]}. The tool results above are steps "
    "1, 2, 3 ... in order. Every claim must use only facts from the steps it cites. At most 5 claims."
)
_llm_calls_today = {"day": None, "n": 0}
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")


def parse_traceparent(header: str | None) -> tuple[str, str | None]:
    """(trace_id, parent_span_id) from a W3C traceparent header; a fresh trace id if it is absent or invalid."""
    m = _TRACEPARENT.match((header or "").strip().lower())
    if m and set(m.group(1)) != {"0"} and set(m.group(2)) != {"0"}:
        return m.group(1), m.group(2)
    return secrets.token_hex(16), None


def _span_id() -> str:
    return secrets.token_hex(8)


def _budget_ok() -> bool:
    day = time.strftime("%Y-%m-%d")
    if _llm_calls_today["day"] != day:
        _llm_calls_today.update(day=day, n=0)
    return _llm_calls_today["n"] < settings.live_daily_llm_cap and llm.budget_left() > 0


def _spend():
    _llm_calls_today["n"] += 1


def _openai_tools(mcp_tools):
    out = []
    for t in mcp_tools:
        params = json.loads(json.dumps(t.input_schema))
        params.get("properties", {}).pop("scope", None)        # the server fixes the scope, not the LLM
        out.append({"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                     "parameters": params}})
    return out


def _compact(env: dict, limit=2000) -> str:
    """What the LLM sees of a tool result: summary, ok and the data without proofs, edge ids and highlights."""
    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items()
                    if k not in ("edge_ids", "nodes", "proof", "certification", "uids", "highlight", "evidence")}
        if isinstance(x, list):
            return [strip(v) for v in x[:8]]
        return x
    text = json.dumps({"ok": env.get("ok"), "summary": env.get("summary"), "data": strip(env.get("data"))},
                      ensure_ascii=False)
    return text[:limit]


async def ask(question: str, scope: str = "demo", mode: str | None = None, emit=None,
              traceparent: str | None = None) -> dict:
    mode = mode or settings.llm_mode
    events, results, seq = [], [], 0
    started = time.perf_counter()
    trace_id, parent_span = parse_traceparent(traceparent)
    root_span = _span_id()

    def send(kind, **payload):
        nonlocal seq
        seq += 1
        ev = {"v": EVENT_SCHEMA_VERSION, "seq": seq, "type": kind, "agent": "chat",
              "t_ms": round((time.perf_counter() - started) * 1000, 1), **payload}
        events.append(ev)
        if emit:
            emit(ev)
        return ev

    send("start", question=question, scope=scope, mode=mode, trace_id=trace_id, span_id=root_span,
         **({"parent_span_id": parent_span} if parent_span else {}))
    async with Client(mcp) as client:
        mcp_tools = await client.list_tools()
        params = {t.name: set((t.input_schema or {}).get("properties", {})) for t in mcp_tools}

        async def call(name, args):
            args = {k: v for k, v in (args or {}).items() if k != "scope"}
            span = _span_id()
            send("tool_call", tool=name, args=dict(args), span_id=span)
            if "scope" in params.get(name, ()):
                args["scope"] = scope                       # set by the server, never by the model
            res = await client.call_tool(name, args, raise_on_error=False)
            text = res.content[0].text if res.content else ""
            if settings.falkordb_host:
                text = text.replace(settings.falkordb_host, "<graph server>")
            env = res.structured_content or {"ok": False, "tool": name, "summary": f"tool error: {text}"[:300],
                                             "data": {}, "entities": []}
            results.append(env)
            send("tool_result", tool=name, span_id=span, ok=env.get("ok"), summary=env.get("summary"), via=env.get("via"),
                 digest=replay.digest(env), queries=(env.get("evidence") or {}).get("query_ids", []),
                 ms=(env.get("evidence") or {}).get("ms"), entities=env.get("entities", []),
                 highlight=env.get("highlight", {"nodes": [], "edges": []}))
            return env

        text, source, problems = None, "template", []
        chain = llm.Chain(trace_id)
        if mode == "live" and _budget_ok():
            try:
                text = await _llm_answer(question, client, mcp_tools, call, send, chain)
                source = "llm"
            except llm.LLMError as exc:
                _drain_failovers(chain, send)
                send("error", stage="llm", message=str(exc)[:200])
        if isinstance(text, list):                  # structured claims: each one checked against its cited steps
            text, report = grounding.assemble(text, results)
            problems = [f"claim {i + 1}: {p}" for i, c in enumerate(report) for p in c["problems"]]
            send("grounding", ok=not problems, problems=problems, claims=report)
            if not any(c["ok"] for c in report) or not text:
                text, source = None, "template"
        elif text is not None:
            problems = grounding.check(text, results)
            if problems:
                send("grounding", ok=False, problems=problems)
                text, source = None, "template"
            else:
                send("grounding", ok=True, problems=[])
        if text is None:
            if not results:
                await router.run(question, call)
            text = templates.answer(results)
    send("answer", text=text, source=source, grounded=source == "template" or not problems,
         tools=[r.get("tool") for r in results], model=chain.models[-1] if source == "llm" and chain.models else None,
         usage={"input_tokens": chain.tokens["input"], "output_tokens": chain.tokens["output"]})
    send("done", ms=round((time.perf_counter() - started) * 1000, 1))
    try:                                        # provenance in the graph (lastlift/memory.py); never changes the answer
        from .. import memory, state
        g = state.graph_name(scope)
        ver = db_version(g)
        memory.record_run(g, "lastlift-chat", question, events, results,
                          next((e for e in events if e["type"] == "answer"), None), ver)
    except Exception:
        pass
    return {"answer": text, "source": source, "events": events, "results": results, "trace_id": trace_id}


def db_version(graph):
    from .. import db
    rs = db.client().select_graph(graph).ro_query("MATCH (m:Meta) RETURN m.state_version LIMIT 1").result_set
    return rs[0][0] if rs else None


def _drain_failovers(chain, send):
    while chain.failovers:
        f = chain.failovers.pop(0)
        send("error", stage="llm_failover", message=f["message"], from_model=f["from_model"], to_model=f["to_model"])


async def _llm_answer(question, client, mcp_tools, call, send, chain):
    """The answer as structured claims (a list) when the model follows CLAIMS_PROMPT, else as text."""
    tools_schema = _openai_tools(mcp_tools)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    step = 0
    for round_no in range(MAX_ROUNDS):
        _spend()
        msg = await asyncio.to_thread(llm.chat, messages, tools_schema, "auto", chain)
        _drain_failovers(chain, send)
        calls = msg.get("tool_calls") or []
        if not calls:
            if round_no == 0:
                raise llm.LLMError("model answered without calling a tool")
            if (msg.get("content") or "").strip():   # it already wrote the answer: no extra call
                content = msg["content"].strip()
                return grounding.parse_claims(content) or content
            break
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for tc in calls:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            env = await call(tc["function"]["name"], args)
            step += 1
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": f"step {step}: {_compact(env)}"})
    _spend()
    messages.append({"role": "user", "content": CLAIMS_PROMPT})
    final = await asyncio.to_thread(llm.chat, messages, tools_schema, "none", chain)
    _drain_failovers(chain, send)
    content = (final.get("content") or "").strip()
    return grounding.parse_claims(content) or content
