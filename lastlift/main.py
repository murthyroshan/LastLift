"""LastLift API. M1 skeleton: health endpoints; tools, agent and MCP arrive in later milestones."""
import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__, db
from .config import settings

STARTED = time.time()

app = FastAPI(title="LastLift", version=__version__, docs_url="/v1/docs", openapi_url="/v1/openapi.json")
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
