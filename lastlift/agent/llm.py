"""LLM provider chain: Groq qwen -> Groq gpt-oss-120b -> Gemini flash-lite; the caller's template is the last tier.

Every tier is an OpenAI-compatible chat-completions endpoint. A tier that fails (rate limit, server error,
timeout, network, no key) is skipped for the rest of the question and the next tier carries on with the same
messages; every switch is recorded on the Chain so the agent can show it in the trace. A daily token budget,
counted from the providers' own usage figures, stops all LLM use before the free quotas run out.
Provider error bodies are never echoed: they can name the account.
"""
import logging
import re
import threading
import time
from dataclasses import dataclass

import httpx

from ..config import settings

log = logging.getLogger("lastlift.llm")
TIMEOUT_S = 30
RETRY_WAIT_S = 8        # one retry on 429 if the provider asks for at most this long (the recorder raises it)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class Tier:
    system: str             # OTel gen_ai.system
    model: str
    url: str
    key_attr: str           # the settings attribute holding the key (the value is never logged)
    parallel_tools: bool = True


def tiers() -> list[Tier]:
    return [Tier("groq", settings.groq_model, GROQ_URL, "groq_api_key"),
            Tier("groq", settings.groq_fallback_model, GROQ_URL, "groq_api_key"),
            Tier("gemini", settings.gemini_chat_model, GEMINI_URL, "gemini_api_key", parallel_tools=False)]


# --- daily token budget (per process; the free tiers reset daily) -------------------------------------------
_lock = threading.Lock()
_usage = {"day": None, "tokens": 0}


def tokens_used_today() -> int:
    with _lock:
        today = time.strftime("%Y-%m-%d")
        if _usage["day"] != today:
            _usage.update(day=today, tokens=0)
        return _usage["tokens"]


def budget_left() -> int:
    return max(0, settings.llm_daily_token_budget - tokens_used_today())


def _spend(tokens: int):
    tokens_used_today()
    with _lock:
        _usage["tokens"] += tokens


def call_tier(tier: Tier, messages, tools=None, tool_choice="auto", max_tokens=700, trace_id=None) -> dict:
    """One request to one tier. Returns the assistant message with `model` and `usage` added; raises LLMError."""
    key = getattr(settings, tier.key_attr, "")
    if not key:
        raise LLMError(f"{tier.model}: no key configured")
    if budget_left() <= 0:
        raise LLMError("daily LLM token budget used up")
    body = {"model": tier.model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
    if tools:
        body.update(tools=tools, tool_choice=tool_choice)
        if tier.parallel_tools:
            body["parallel_tool_calls"] = True
    started = time.perf_counter()
    for attempt in (1, 2):
        try:
            r = httpx.post(tier.url, json=body, timeout=TIMEOUT_S, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as exc:
            raise LLMError(f"{tier.model}: request failed ({type(exc).__name__})") from exc
        if r.status_code != 429 or attempt == 2:
            break
        try:
            wait = float(r.headers.get("retry-after", "0"))
        except ValueError:
            wait = 0.0
        if not 0 < wait <= RETRY_WAIT_S:
            break
        time.sleep(wait)
    if r.status_code != 200:
        raise LLMError(f"{tier.model}: LLM HTTP {r.status_code}" + (" (rate limit)" if r.status_code == 429 else ""))
    try:
        data = r.json()
        msg = data["choices"][0]["message"]
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMError(f"{tier.model}: malformed response") from exc
    usage = data.get("usage") or {}
    _spend(int(usage.get("total_tokens") or 0))
    # Attribute names from the OpenTelemetry GenAI semantic conventions, so any OTel log pipeline can read them.
    log.info("gen_ai chat", extra={"otel": {
        "trace_id": trace_id, "gen_ai.operation.name": "chat", "gen_ai.system": tier.system,
        "gen_ai.request.model": tier.model, "gen_ai.response.model": data.get("model", tier.model),
        "gen_ai.usage.input_tokens": usage.get("prompt_tokens"),
        "gen_ai.usage.output_tokens": usage.get("completion_tokens"),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1)}})
    if msg.get("content"):
        msg["content"] = _THINK.sub("", msg["content"]).strip()
    msg["model"] = tier.model
    msg["usage"] = {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")}
    return msg


class Chain:
    """One question's walk down the tiers. A failed tier stays skipped for the rest of the question."""

    def __init__(self, trace_id=None):
        self.trace_id = trace_id
        self.tiers = tiers()
        self.at = 0
        self.failovers: list[dict] = []     # drained by the agent into trace events
        self.models: list[str] = []         # the model that served each call
        self.tokens = {"input": 0, "output": 0}

    def chat(self, messages, tools=None, tool_choice="auto", max_tokens=700) -> dict:
        while self.at < len(self.tiers):
            tier = self.tiers[self.at]
            try:
                msg = call_tier(tier, messages, tools, tool_choice, max_tokens, self.trace_id)
            except LLMError as exc:
                self.at += 1
                nxt = self.tiers[self.at].model if self.at < len(self.tiers) else "template"
                self.failovers.append({"from_model": tier.model, "to_model": nxt, "message": str(exc)[:200]})
                if "budget" in str(exc):
                    break
                continue
            self.models.append(msg["model"])
            self.tokens["input"] += msg["usage"]["input_tokens"] or 0
            self.tokens["output"] += msg["usage"]["output_tokens"] or 0
            return msg
        raise LLMError("every LLM tier failed")


def chat(messages, tools=None, tool_choice="auto", chain: Chain | None = None, max_tokens=700) -> dict:
    """Return the assistant message from the first tier that answers. Raises LLMError when none does."""
    return (chain or Chain()).chat(messages, tools, tool_choice, max_tokens)
