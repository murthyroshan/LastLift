"""LastLift API: health, the agent's tools over HTTP, and the station graph contract.
The agent and MCP server arrive in later milestones and call the same tool registry."""
import inspect
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__, db, state, station_view, tools
from .config import settings

STARTED = time.time()
log = logging.getLogger("lastlift")


@asynccontextmanager
async def lifespan(_app):
    try:
        state.sweep_stale_what_ifs()        # what-if copies never outlive the process that made them
    except Exception as exc:                # graph server not up yet: /healthz reports it
        log.warning("what-if sweep skipped: %s", exc)
    yield


app = FastAPI(title="LastLift", version=__version__, docs_url="/v1/docs", openapi_url="/v1/openapi.json",
              lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


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
