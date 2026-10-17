"""Deterministic answers built only from tool envelopes (used when the LLM is off, fails or is ungrounded)."""
from ..wording import DISCLAIMERS

FOOTER = "Results describe the open-data model and may differ on site. Check mbta.com/alerts/access."


def answer(results: list[dict]) -> str:
    if not results:
        return ("I can only answer questions about step-free (lift) access at MBTA stations. "
                "Try a station name or a lift number. " + FOOTER)
    parts = []
    # resolve_place only finds ids for the next tool; it is shown only when it is all there is.
    shown = [r for r in results if r.get("tool") != "resolve_place"] or results
    for r in shown:
        s = r.get("summary", "").strip()
        if not s:
            continue
        if s.startswith("cannot assess"):
            s = s + ". " + DISCLAIMERS["cannot_assess"]
        parts.append(s[0].upper() + s[1:] + ("" if s.endswith(".") else "."))
    return " ".join(parts) + " " + FOOTER
