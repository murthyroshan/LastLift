"""Rule-based router: answers without an LLM by choosing tools from the question. It calls tools only through
the `call` function it is given (the agent passes its MCP client), never the registry directly."""
import re

BOARD = re.compile(r"\b(onto|board|boarding|get on|reach)\b")
EXIT = re.compile(r"\b(off|exit|get out|leave|leaving|arrive|arriving)\b")


def _lifts(q):
    return re.findall(r"\b(\d{3,4})\b", q)


async def _stations(q, call):
    """Stations named in the question (resolved via resolve_place, kept only if their name is in the text)."""
    ql = q.lower()
    m = re.search(r"\bfrom\b(.+?)\bto\b(.+)", ql)          # "I need to get from A to B": split at A..to..B
    sides = [m.group(1), m.group(2)] if m else [ql]
    found = []
    for side in sides:
        side = re.sub(r"\b(from|route|get|how|do|i|can|need|the|at|is|right|now|today)\b", " ", side)
        res = await call("resolve_place", {"query": side})
        for s in (res.get("data") or {}).get("stations", []):
            names = {s["name"].lower(), s["name"].lower().split("/")[0].strip()}
            if any(n and n in ql for n in names) and s["station_id"] not in [f["station_id"] for f in found]:
                found.append(s)
                break
    return found


def _platform(redundancy, q):
    ql = q.lower()
    for p in (redundancy.get("data") or {}).get("platforms", []):
        label = (p.get("platform_name") or "").lower()
        first = label.split(" ")[0] if label else ""
        if first and len(first) > 3 and first in ql:
            return p["stop_id"]
    return None


async def run(question: str, call) -> None:
    q = question.lower()
    lifts = _lifts(q)
    if lifts and re.search(r"what if|if .*\b(fail|fails|close|closes|closed|break)|simulate", q):
        await call("what_if_close", {"facility_ids": lifts})
        return
    if re.search(r"journeys?|network|cut off|between stations|critical pair|last link|whole system", q):
        await call("network_impact", {"facility_ids": lifts} if lifts else {})
        return
    if lifts and re.search(r"ticket|draft|issue", q):
        await call("draft_action", {"facility_id": lifts[0]})
        return
    if lifts and re.search(r"history|how often|before|record", q):
        await call("lift_history", {"facility_id": lifts[0]})
        return
    if re.search(r"\b(order|sequence)\b", q) and re.search(r"repair|fix|reopen", q):
        await call("repair_order", {})
        return
    if re.search(r"repair|priorit|fix first|protect", q):
        await call("repair_priority", {})
        return
    if lifts and re.search(r"\b(out|closed|down|broken|affected|changed)\b", q):
        info = await call("resolve_place", {"query": lifts[0]})
        lift = next(iter((info.get("data") or {}).get("lifts", [])), None)
        if lift and lift["modelled"] and lift["closed"]:       # already closed: show the station as it is now
            await call("platform_redundancy", {"station_id": lift["station_id"]})
        else:                                                  # working lift: simulate; unmodelled: cannot assess
            await call("what_if_close", {"facility_ids": lifts})
        return
    stations = await _stations(question, call)
    if len(stations) >= 2:
        await call("step_free_route", {"from_station": stations[0]["station_id"], "to_station": stations[1]["station_id"]})
        return
    if stations:
        sid = stations[0]["station_id"]
        red = await call("platform_redundancy", {"station_id": sid})
        stop = _platform(red, question)
        if stop and BOARD.search(q):
            await call("step_free_route", {"from_station": sid, "to_platform": stop})
        elif stop and EXIT.search(q):
            await call("step_free_route", {"from_station": sid, "from_platform": stop})
        return
    if re.search(r"closed|closure|out of service|right now|today|lifts? (are )?out", q):
        await call("current_closures", {})
        return
    if lifts:
        await call("resolve_place", {"query": " ".join(lifts)})
