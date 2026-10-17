"""LastLift API: health, the tools over HTTP and MCP (/mcp/), the agent (/api/ask, POST or SSE) and the
station graph contract. HTTP, MCP and the agent all use the one tool registry."""
import asyncio
import inspect
import json
import logging
import os
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
    }


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
