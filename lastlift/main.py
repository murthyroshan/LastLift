"""LastLift API: health, the tools over HTTP and MCP (/mcp/), the agent (/api/ask, POST or SSE) and the
station graph contract. HTTP, MCP and the agent all use the one tool registry."""
import asyncio
import inspect
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from . import __version__, db, incidents, live, state, station_view, tools, wording
from .agent import loop as agent
from .mcp_server import mcp
from .config import settings

STARTED = time.time()
log = logging.getLogger("lastlift")
mcp_app = mcp.http_app(path="/", stateless_http=True)        # MCP over streamable HTTP at /mcp/


@asynccontextmanager
async def lifespan(_app):
    try:
        state.sweep_stale_what_ifs()        # what-if copies never outlive the process that made them
        for scope in ("base", "demo", "live"):
            if state.exists(state.graph_name(scope)):
                incidents.sync(scope)       # incident memory rebuilt from the committed harvest
    except Exception as exc:                # graph server not up yet: /healthz reports it
        log.warning("boot sync skipped: %s", exc)
    poller = asyncio.create_task(live.run_forever(settings.live_poll_s)) if settings.live_feed == "on" else None
    try:
        async with mcp_app.lifespan(mcp_app):
            yield
    finally:
        if poller:
            poller.cancel()


app = FastAPI(title="LastLift", version=__version__, docs_url="/v1/docs", openapi_url="/v1/openapi.json",
              lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "traceparent"],
)
app.mount("/mcp", mcp_app)


@app.exception_handler(RedisConnectionError)
@app.exception_handler(RedisTimeoutError)
async def graph_unavailable(_request, exc):
    """Fail loudly: without the graph there is no answer, never a guessed or empty one."""
    log.error("graph server unavailable: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={
        "ok": False, "error": "graph_unavailable",
        "summary": "The graph server is unreachable, so LastLift gives no answer. "
                   "Check mbta.com/alerts/access for current elevator status.",
        "data": None})


def _rss_mb() -> float | None:
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        return None
    return None


@app.get("/healthz", include_in_schema=False)
def healthz():
    """Render health check: fast, never touches the LLM. 503 when the graph server is unreachable."""
    if db.ping():
        return {"status": "ok"}
    return JSONResponse({"status": "degraded", "reason": "graph server unreachable"}, status_code=503)


@app.get("/v1/health")
def health():
    """Wake/boot status for the website's waking banner."""
    up = db.ping()
    return {
        "status": "ok" if up else "degraded",
        "version": __version__,
        "env": settings.app_env,
        "falkordb": {"reachable": up, "module_version": db.module_version() if up else None},
        "llm_mode": settings.llm_mode,
        "actions_mode": settings.actions_mode,
        "uptime_s": round(time.time() - STARTED, 1),
        "rss_mb": _rss_mb(),
        "pid": os.getpid(),
        "graph_memory_mb": _graph_memory() if up else None,
    }


def _graph_memory() -> dict:
    """GRAPH.MEMORY USAGE per scope graph (FalkorDB's own accounting, in MB)."""
    out = {}
    for scope in ("base", "demo", "live"):
        name = state.graph_name(scope)
        try:
            r = db.client().connection.execute_command("GRAPH.MEMORY", "USAGE", name)
            out[scope] = dict(zip(r[::2], r[1::2])).get("total_graph_sz_mb")
        except Exception:                   # graph missing or command unsupported: report nothing
            out[scope] = None
    return out


_PLAN_CALLS: list[float] = []
PLAN_LIMIT_PER_MIN = 10


def _sample_params(g, qid: str) -> dict | None:
    """Fixed example parameters (Alewife, lifts 813/884/885) for the read queries that take parameters."""
    cx = {"cx": "place-alfcl"}
    simple = {
        "Q_COMPLEX_FLOW_EDGES": cx, "Q_COMPLEX_PLATFORMS": cx, "Q_COMPLEX_STREETS": cx, "Q_STATION_NODES": cx,
        "Q_STATION_EDGES": cx, "Q_STATION_PLATFORMS": cx, "Q_CLOSED_AT_COMPLEX": cx, "Q_PLATFORM_CUTS": cx,
        "Q_STATION": {"sid": "place-alfcl"}, "Q_STATION_UNMODELLED_LIFTS": {"sid": "place-wrcst"},
        "Q_STATION_SEARCH": {"q": "alewife*"}, "Q_LIFT_INFO": {"fid": "813"}, "Q_LIFT_HISTORY": {"fid": "885"},
        "Q_LIFT_INCIDENT_COUNT": {"fid": "885"}, "Q_MODELLED_LIFTS": {"fids": ["813", "885"]},
        "Q_LIFT_COMPLEXES": {"fids": ["813"]}, "Q_LIFT_BLAST": {"fids": ["813", "884"]},
        "Q_REACHES_FROM": {"sid": "place-rbmnl"}, "Q_DOMINATES_FOR": {"fid": "884"},
    }
    if qid in simple:
        return simple[qid]
    if qid == "Q_MAXFLOW":
        src = g.ro_query("MATCH (s:Street {cx:'place-alfcl'}) RETURN collect(s.uid)").result_set[0][0]
        dst = g.ro_query("MATCH (p:Node:Platform {cx:'place-alfcl'}) RETURN p.uid ORDER BY p.uid LIMIT 1").result_set
        return {"src": src, "dst": [dst[0][0]] if dst else []}
    return {} if qid in ("Q_LOST_NOW", "Q_NEWLY_LAST", "Q_PRIORITY", "Q_CLOSED_FACILITIES", "Q_META",
                         "Q_CRITICAL_PAIRS", "Q_CONDITIONAL", "Q_NETWORK_SPOF") else None


@app.get("/v1/queries/{query_id}/plan")
def query_plan(query_id: str, mode: Literal["explain", "profile"] = "explain"):
    """FalkorDB's execution plan for one catalogued read query, with fixed example parameters.
    explain: GRAPH.EXPLAIN on the demo graph (nothing runs). profile: GRAPH.PROFILE on a private copy of the
    demo graph (the query runs; records and ms per operator). Write queries are refused; 10 calls a minute."""
    from . import queries
    q = getattr(queries, query_id, None) if query_id.startswith("Q_") else None
    if not isinstance(q, str):
        raise HTTPException(404, "unknown query id (see /v1/queries)")
    if re.search(r"\b(CREATE|SET|DELETE|MERGE|REMOVE)\b", q):
        raise HTTPException(403, "write queries are never explained or profiled here")
    now = time.time()
    _PLAN_CALLS[:] = [t for t in _PLAN_CALLS if now - t < 60]
    if len(_PLAN_CALLS) >= PLAN_LIMIT_PER_MIN:
        raise HTTPException(429, "at most 10 plans a minute")
    _PLAN_CALLS.append(now)
    demo = tools._scope_graph("demo")
    g = db.client().select_graph(demo)
    params = _sample_params(g, query_id)
    if params is None:
        raise HTTPException(404, "no example parameters for this query")
    if mode == "profile":
        name = state.graph_name(f"wi_profile_{os.getpid()}")
        if not state.exists(name):
            db.client().connection.execute_command("GRAPH.COPY", demo, name)
        plan = db.client().select_graph(name).profile(q, params)
        graph = name
    else:
        plan = g.explain(q, params)
        graph = demo
    return {"query_id": query_id, "mode": mode, "graph": graph, "params": params, "query": q,
            "plan": [str(line).rstrip() for line in plan.plan if str(line).strip()]}


def _call(fn, kwargs):
    try:
        return fn(**kwargs)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/v1/tools")
def list_tools():
    """The fixed tool registry (the same functions the agent and MCP clients call)."""
    return [{"name": name, "description": inspect.getdoc(fn).splitlines()[0],
             "params": {p.name: (None if p.default is inspect.Parameter.empty else p.default)
                        for p in inspect.signature(fn).parameters.values()}}
            for name, fn in tools.REGISTRY.items()]


@app.post("/v1/tools/{name}")
def call_tool(name: str, args: dict = Body(default_factory=dict)):
    """Run one tool with JSON arguments; returns the tool envelope."""
    fn = tools.REGISTRY.get(name)
    if fn is None:
        raise HTTPException(404, f"unknown tool {name}")
    allowed = set(inspect.signature(fn).parameters)
    extra = sorted(set(args) - allowed)
    if extra:
        raise HTTPException(422, f"unknown argument(s) for {name}: {', '.join(extra)}")
    return _call(fn, args)


@app.get("/v1/stations/{station_id}/graph")
def station_graph(station_id: str, dir: Literal["board", "exit"] = "board",
                  scope: Literal["demo", "live", "base"] = "demo", scenario: str | None = Query(None, max_length=64)):
    """The station graph contract for the x-ray (contracted nodes, edges, platforms, routes, receipt)."""
    if scope != "base":
        tools._scope_graph(scope)           # make sure the scope graph exists and is synced
    return _call(station_view.view, {"station_id": station_id, "direction": dir, "scope": scope, "scenario": scenario})


@app.get("/v1/live")
def live_status():
    """The live feed: on/off, when it last polled the MBTA, whether that is stale (over 5 minutes), the state
    version and the modelled closed lifts. With the feed off the live scope is the committed alert harvest."""
    return live.status()


@app.get("/v1/disclaimers")
def disclaimers():
    """The exact disclaimer texts every surface uses (footer, validation, partial, cannot-assess, ...)."""
    return wording.DISCLAIMERS


def _require_graph():
    if not db.ping():                       # fail loudly before the agent starts, never a guessed answer
        raise RedisConnectionError("graph server unreachable")


@app.post("/api/ask")
async def ask(body: dict = Body(...), traceparent: str | None = Header(default=None)):
    """Ask the agent; returns the answer, its source (llm or template), the W3C trace id and every event of the run.
    A `traceparent` header joins the caller's trace."""
    question = str(body.get("question", "")).strip()[:500]
    scope = body.get("scope", "demo")
    if not question or scope not in tools.SCOPES:
        raise HTTPException(400, "question (non-empty) and scope (demo|live|base) required")
    _require_graph()
    r = await agent.ask(question, scope=scope, traceparent=traceparent)
    return {"answer": r["answer"], "source": r["source"], "trace_id": r["trace_id"], "events": r["events"]}


@app.get("/api/ask")
async def ask_stream(q: str = Query(..., min_length=1, max_length=500),
                     scope: Literal["demo", "live", "base"] = "demo",
                     traceparent: str | None = Header(default=None)):
    """The same run as a server-sent event stream (one SSE event per agent event, ending with 'done')."""
    _require_graph()
    queue: asyncio.Queue = asyncio.Queue()

    async def run():
        try:
            await agent.ask(q, scope=scope, emit=queue.put_nowait, traceparent=traceparent)
        except Exception as exc:            # surface the failure in the stream, then end it
            queue.put_nowait({"v": 1, "seq": 0, "type": "error", "t_ms": 0, "stage": "server",
                              "message": type(exc).__name__})
            queue.put_nowait({"v": 1, "seq": 0, "type": "done", "t_ms": 0, "ms": 0})

    task = asyncio.create_task(run())

    async def stream():
        try:
            while True:
                ev = await queue.get()
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev["type"] == "done":
                    break
        finally:
            task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/v1/queries")
def query_catalogue():
    """Every Cypher statement LastLift runs (the Q_* constants), so any answer's query ids can be read in full."""
    from . import queries
    return {name: getattr(queries, name) for name in sorted(dir(queries)) if name.startswith("Q_")}
