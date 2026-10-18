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

from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
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
OPS_TOKEN = os.environ.get("OPS_MCP_TOKEN", "")
ops_app = None
if OPS_TOKEN:                                                # operations MCP (approvals): only with a token set
    from .mcp_server import build_ops
    ops_app = build_ops(OPS_TOKEN).http_app(path="/", stateless_http=True)


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
            if ops_app is not None:
                async with ops_app.lifespan(ops_app):
                    yield
            else:
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
    allow_headers=["Content-Type", "traceparent", "Idempotency-Key"],
)
app.mount("/mcp", mcp_app)
if ops_app is not None:
    app.mount("/mcp-ops", ops_app)


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


_STT_CALLS: list[float] = []
STT_PER_MIN, STT_PER_DAY = 20, 200


@app.post("/v1/stt")
async def speech_to_text(request: Request):
    """Eyes-free mode's fallback when the browser has no speech recognition: up to 8 s of audio (webm/ogg/wav body)
    transcribed by Groq Whisper (English, biased to station names). Capped at 20 a minute and 200 a day."""
    if not settings.groq_api_key:
        raise HTTPException(503, "speech recognition is not configured")
    audio = await request.body()
    if not audio or len(audio) > 2_000_000:
        raise HTTPException(400, "send up to 2 MB of audio")
    now = time.time()
    _STT_CALLS[:] = [t for t in _STT_CALLS if now - t < 86400]
    if len([t for t in _STT_CALLS if now - t < 60]) >= STT_PER_MIN or len(_STT_CALLS) >= STT_PER_DAY:
        raise HTTPException(429, "speech recognition limit reached; type the question instead")
    _STT_CALLS.append(now)
    import httpx
    ctype = request.headers.get("content-type", "audio/webm").split(";")[0]
    ext = {"audio/ogg": "ogg", "audio/wav": "wav", "audio/mpeg": "mp3"}.get(ctype, "webm")
    prompt = ("Boston MBTA stations: Alewife, Revere Beach, Wonderland, Chinatown, Back Bay, South Station, "
              "Downtown Crossing, Park Street, Harvard, Kendall, North Station, elevator")
    try:
        r = await asyncio.to_thread(lambda: httpx.post(
            "https://api.groq.com/openai/v1/audio/transcriptions", timeout=30,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            data={"model": "whisper-large-v3-turbo", "language": "en", "prompt": prompt, "response_format": "json"},
            files={"file": (f"speech.{ext}", audio, ctype)}))
    except httpx.HTTPError:
        raise HTTPException(502, "speech recognition unavailable")
    if r.status_code != 200:
        raise HTTPException(502, f"speech recognition HTTP {r.status_code}")
    return {"text": (r.json().get("text") or "").strip()}


@app.post("/v1/verify-cut")
def verify_cut(body: dict = Body(...)):
    """Re-check a minimum cut in FalkorDB: close the cut's lifts on a throwaway copy of the scope and run the
    certified max-flow for that platform-direction. {station_id, stop_id, dir, cut: [facility ids], scope?}"""
    from . import redundancy
    from .queries import Q_COMPLEX_PLATFORMS, Q_COMPLEX_STREETS, Q_STATION
    scope = body.get("scope", "demo")
    cut, stop, d = [str(x) for x in body.get("cut") or []], str(body.get("stop_id", "")), body.get("dir")
    if scope not in ("demo", "live") or d not in ("board", "exit") or not cut or len(cut) > 6:
        raise HTTPException(400, "need stop_id, dir board|exit, and a cut of 1-6 lift ids")
    _require_graph()
    started = time.perf_counter()
    tools._scope_graph(scope)
    res = state.what_if(scope, cut)
    g = db.client().select_graph(res["copy"])
    srs = g.ro_query(Q_STATION, {"sid": body.get("station_id")}).result_set
    if not srs:
        raise HTTPException(404, "unknown station")
    cx = srs[0][2]
    streets = g.ro_query(Q_COMPLEX_STREETS, {"cx": cx}).result_set[0][0]
    uids = {r[0]: r[1] for r in g.ro_query(Q_COMPLEX_PLATFORMS, {"cx": cx}).result_set}
    if stop not in uids:
        raise HTTPException(404, "unknown platform at this station")
    edges, lf = redundancy.complex_edges(g, cx)
    src, dst = (streets, uids[stop]) if d == "board" else (uids[stop], streets)
    r = redundancy.direction(g, edges, lf, src, dst)
    return {"cut": cut, "stop_id": stop, "dir": d, "max_flow": 0 if r.k is None and not r.at_grade else r.k,
            "at_grade": r.at_grade, "certified": r.outcome, "graph": res["copy"],
            "ms": round((time.perf_counter() - started) * 1000, 1)}


@app.get("/v1/incidents")
def agent_incidents(scope: Literal["demo", "live"] = "demo"):
    """The Analyst's assessments (playbook, verdict, platform-directions found, whether still current)."""
    from .agents import roles
    return {"scope": scope, "assessments": roles.incidents(scope)}


@app.get("/v1/approvals")
def agent_approvals(scope: Literal["demo", "live"] = "demo", status: str | None = None):
    """Action proposals from the Dispatcher (proposed / approved_draft / rejected / superseded / dry_run)."""
    from .agents import roles
    return {"scope": scope, "proposals": roles.proposals(scope, status), "policy": roles.POLICY}


@app.get("/v1/answers/{trace_id}")
def answer_status(trace_id: str, scope: Literal["demo", "live"] = "demo"):
    """Whether an earlier agent answer is still true: it is marked stale, in the graph, as soon as any lift it read
    changes state. The chat polls this for each live answer."""
    from . import memory
    if not re.fullmatch(r"[0-9a-f]{32}", trace_id):
        raise HTTPException(400, "trace id must be 32 hex characters")
    return _call(memory.answer_status, {"graph": state.graph_name(scope), "trace_id": trace_id})


@app.post("/v1/approvals/{pid}")
def agent_decide(pid: str, request: Request, body: dict = Body(...), scope: Literal["demo", "live"] = "demo",
                 idempotency_key: str | None = Header(default=None)):
    """A human decision: {"decision": "approve" | "reject"}. Needs an Idempotency-Key header; a repeat with the same
    key returns the first result. Refused if the graph changed since the proposal (the proposal is superseded).
    With ACTIONS_MODE=file an approval files a real GitHub issue, so it is taken only from the operator's own machine."""
    from .agents import roles
    if settings.actions_mode == "file" and (request.client.host if request.client else "") not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "filing tickets is enabled only on the operator's machine")
    if body.get("decision") not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve or reject")
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header required")
    return _call(roles.decide, {"scope": scope, "pid": pid, "decision": body["decision"], "idem_key": idempotency_key})


@app.post("/internal/tick", include_in_schema=False)
async def agent_tick(scope: Literal["demo", "live"] = "live", x_tick_token: str | None = Header(default=None)):
    """Monitor -> Analyst -> Dispatcher once (for a scheduled job). Needs the TICK_TOKEN secret."""
    from .agents import roles
    if not settings.tick_token or x_tick_token != settings.tick_token:
        raise HTTPException(403, "tick token required")
    _require_graph()
    r = await roles.tick(scope)
    return {k: r[k] for k in ("scope", "trace_id", "assessments")}


@app.get("/v1/eval/latest")
def eval_latest():
    """The agent evaluation (eval/protocol.md): every system's metrics with Wilson intervals, and the baselines."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "eval", "latest.json")
    if not os.path.isfile(path):
        raise HTTPException(404, "no evaluation run yet")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


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
