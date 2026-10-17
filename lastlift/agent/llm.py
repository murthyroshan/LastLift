"""Groq chat-completions client (OpenAI-compatible), with tool calling. One request at a time; no retries
beyond one fallback model, so a failure falls through to the deterministic template quickly."""
import re
import time

import httpx

from ..config import settings

URL = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT_S = 30
RETRY_WAIT_S = 8        # one retry on 429 if the provider asks for at most this long (the recorder raises it)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class LLMError(RuntimeError):
    pass


def chat(messages, tools=None, tool_choice="auto", model=None, max_tokens=700) -> dict:
    """Return the assistant message dict. Raises LLMError on any failure."""
    if not settings.groq_api_key:
        raise LLMError("no LLM key configured")
    body = {"model": model or settings.groq_model, "messages": messages, "temperature": 0,
            "max_tokens": max_tokens}
    if tools:
        body.update(tools=tools, tool_choice=tool_choice, parallel_tool_calls=True)
    for attempt in (1, 2):
        try:
            r = httpx.post(URL, json=body, timeout=TIMEOUT_S,
                           headers={"Authorization": f"Bearer {settings.groq_api_key}"})
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {type(exc).__name__}") from exc
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
        # Never echo the provider's body: it names the account. Status alone is enough for the trace.
        raise LLMError(f"LLM HTTP {r.status_code}" + (" (rate limit)" if r.status_code == 429 else ""))
    msg = r.json()["choices"][0]["message"]
    if msg.get("content"):
        msg["content"] = _THINK.sub("", msg["content"]).strip()
    return msg
