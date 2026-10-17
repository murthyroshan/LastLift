"""Settings: environment variables first, then the local ../.env file (dev only).

Production (Render) injects variables; no file exists there. Values are never logged.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_env_file() -> dict[str, str]:
    path = Path(os.environ.get("ENV_FILE", REPO_ROOT.parent / ".env"))
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("'\"")
    return values


def _get(file_values: dict[str, str], key: str, default: str = "") -> str:
    return os.environ.get(key) or file_values.get(key) or default


@dataclass(frozen=True)
class Settings:
    app_env: str
    falkordb_host: str
    falkordb_port: int
    falkordb_username: str | None
    falkordb_password: str | None
    graph_prefix: str
    groq_api_key: str = field(repr=False)
    groq_model: str
    groq_fallback_model: str
    gemini_api_key: str = field(repr=False)
    gemini_chat_model: str
    mbta_api_key: str = field(repr=False)
    github_token: str = field(repr=False)
    ops_repo: str
    llm_mode: str
    actions_mode: str
    live_feed: str
    allowed_origins: tuple[str, ...]
    live_daily_llm_cap: int
    llm_daily_token_budget: int
    live_poll_s: int

    def graph(self, name: str) -> str:
        """Full graph name, e.g. graph('base') -> 'dev_ll_base' locally, 'll_base' in production."""
        return f"{self.graph_prefix}_{name}"


def load_settings() -> Settings:
    f = _load_env_file()
    return Settings(
        app_env=_get(f, "APP_ENV", "development"),
        falkordb_host=_get(f, "FALKORDB_HOST", "127.0.0.1"),
        falkordb_port=int(_get(f, "FALKORDB_PORT", "6379")),
        falkordb_username=_get(f, "FALKORDB_USERNAME") or None,
        falkordb_password=_get(f, "FALKORDB_PASSWORD") or None,
        graph_prefix=_get(f, "GRAPH_PREFIX", "dev_ll"),
        groq_api_key=_get(f, "GROQ_API_KEY"),
        groq_model=_get(f, "GROQ_MODEL", "qwen/qwen3.8-27b"),
        groq_fallback_model=_get(f, "GROQ_FALLBACK_MODEL", "openai/gpt-oss-120b"),
        gemini_api_key=_get(f, "GEMINI_API_KEY"),
        gemini_chat_model=_get(f, "GEMINI_CHAT_MODEL", "gemini-3.1-flash-lite"),
        mbta_api_key=_get(f, "MBTA_API_KEY"),
        github_token=_get(f, "GITHUB_TOKEN"),
        ops_repo=_get(f, "OPS_REPO", "murthyroshan/lastlift-ops"),
        llm_mode=_get(f, "LLM_MODE", "replay"),
        actions_mode=_get(f, "ACTIONS_MODE", "draft"),
        live_feed=_get(f, "LIVE_FEED", "off"),
        allowed_origins=tuple(o.strip() for o in _get(f, "ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()),
        live_daily_llm_cap=int(_get(f, "LIVE_DAILY_LLM_CAP", "150")),
        llm_daily_token_budget=int(_get(f, "LLM_DAILY_TOKEN_BUDGET", "400000")),
        live_poll_s=int(_get(f, "LIVE_POLL_S", "60")),
    )


settings = load_settings()
