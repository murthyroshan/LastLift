"""Exact user-facing disclaimers and the wording rules every surface follows.

The texts are fixed: the API serves them at /v1/disclaimers, the web app and README reuse them, and
scripts/copy_lint.py checks that nothing user-facing uses the phrases in NEVER_SAY.
"""
import re

# The data sources named here are the ones LastLift uses today. Add "Open Data Portal alert archives"
# to the footer only when the historical alert archive is actually loaded.
DISCLAIMERS = {
    "footer": (
        "Unofficial decision-support prototype. Not affiliated with or endorsed by the MBTA or MassDOT. "
        "Uses MBTA GTFS and V3 API data under the MassDOT Developers License Agreement. Data may be "
        "incomplete or out of date. Always check mbta.com/alerts/access before travelling. "
        "Elevator status line 617-222-2828; customer support 617-222-3200 (TTY 711)."
    ),
    "validation": (
        "Agreement with MBTA's published alternative-route text, labelled by one person. Small samples, "
        "with 95% intervals shown. Disagreements are listed in full."
    ),
    "history": (
        "Based on closures MBTA reported in public alerts, replayed through today's station layout data. "
        "Reported closures may differ from actual elevator status, and station layouts changed during this period."
    ),
    "risk": (
        "A historical frequency estimate. It is not a prediction that any elevator will fail, and not an MBTA figure."
    ),
    "equity": (
        "Residents near a station, not riders. ACS 5-year estimates with margins of error. A planning context only."
    ),
    "data_report": "Sent as a courtesy by an independent developer. We may be misreading the data.",
    "policy_brief": (
        "Independent analysis of public data, offered for discussion. Not legal advice, and not a compliance assessment."
    ),
    "video_end_card": "Unofficial. Not affiliated with the MBTA. Public data. AI-assisted build, disclosed in the README.",
    "partial": (
        "A step-free route exists in the station layout data, but MBTA's alert advises a different route. "
        "Follow MBTA's advice on site."
    ),
    "cannot_assess": (
        "MBTA has not published a station layout for this station, so LastLift cannot check alternatives. "
        "See MBTA's alert."
    ),
}

# Phrases no user-facing text may use (case-insensitive regular expressions), with the reason.
NEVER_SAY = {
    r"\bstranded\b": "say 'loses step-free access in the open-data model'",
    r"\btrapped\b": "say 'loses step-free access in the open-data model'",
    r"\bsafe(ly)?\b": "never promise safety",
    r"\bguarantee[sd]?\b": "never guarantee a route",
    r"\bconfirmed accessible\b": "LastLift does not confirm conditions on site",
    r"\b(is|are|was|were|remains?|stays?) (fully |still |now )?(in)?accessible\b": "never call a place accessible or inaccessible outright",
    r"\bMBTA says\b": "never attribute LastLift's output to the MBTA",
    r"\bpredicts? (lift |elevator )?failures?\b": "LastLift does not predict failures",
    r"\bADA (violation|compliance|compliant)\b": "no legal or compliance claims",
    r"\b100 ?% accurate\b": "report n and the interval instead",
    r"\b\d[\d,]* disabled people\b": "no invented counts of affected people",
    r"\bshuttle has been requested\b": "LastLift never requests services",
    r"\brequest The RIDE\b": "LastLift never requests services",
}
_NEVER = [(re.compile(p, re.IGNORECASE), why) for p, why in NEVER_SAY.items()]


def violations(text: str) -> list[tuple[str, str]]:
    """(phrase found, reason) for every banned phrase in `text`."""
    return [(m.group(0), why) for rx, why in _NEVER for m in rx.finditer(text)]
