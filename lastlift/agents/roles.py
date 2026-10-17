"""Monitor, Analyst and Dispatcher (see lastlift/agents/__init__.py), and tick() which runs them in order."""
import hashlib
import time
import uuid

from fastmcp import Client

from .. import alerts, db, state, tools
from ..config import settings
from ..mcp_server import mcp

CHRONIC_QUANTILE = 0.75   # +CHRONIC: the lift is in the top quarter of modelled lifts by closures in the archive's
                          # last 12 months (computed from the graph on every tick)

# Action policy table (printed in the README). Nothing is filed by this module: approved tickets are drafts until
# the ticket executor (GitHub) runs; rider notices are dry runs unless a notifier is configured.
POLICY = {
    "repair_ticket": {"approval": "human", "for": ("ACCESS_LOST",)},
    "protect_ticket": {"approval": "human", "for": ("PREVENTIVE",)},
    "rider_notice": {"approval": "auto", "for": ("ACCESS_LOST",)},
}

Q_LIFT_FACTS = (
    "MATCH (l:Lift) WHERE l.facility_id = $fid WITH l ORDER BY l.uid LIMIT 1 "
    "OPTIONAL MATCH (s:Station {uid:l.station_id}) "
    "RETURN l.uid, (l:Node) AS modelled, l.cx, l.station_id, coalesce(s.has_pathways, false), l.outages_12m"
)
Q_ACCESS_LOST_BY = (
    "MATCH (p:Node:Platform {cx:$cx}) WHERE (p.k_board = 0 AND p.k_board_base > 0 AND $fid IN p.cut_board) "
    "OR (p.k_exit = 0 AND p.k_exit_base > 0 AND $fid IN p.cut_exit) "
    "RETURN DISTINCT p.stop_id, p.name, p.platform_name, p.k_board_base, p.k_board, p.k_exit_base, p.k_exit, "
    "$fid IN p.cut_board AND p.k_board = 0, $fid IN p.cut_exit AND p.k_exit = 0 ORDER BY p.stop_id"
)
Q_NEW_LAST_AT = (
    "MATCH (p:Node:Platform {cx:$cx})-[n:DEPENDS_NOW]->(l:Lift) WHERE NOT (p)-[:DEPENDS_ON {dir:n.dir}]->(l) "
    "RETURN l.facility_id, collect(DISTINCT p.stop_id + ' ' + n.dir) ORDER BY l.facility_id"
)
Q_META_VERSION = "MATCH (m:Meta) RETURN m.state_version LIMIT 1"
Q_GUARD = "MATCH (a:Assessment {aid:$aid}) MATCH (m:Meta) WHERE a.state_version = m.state_version RETURN count(a)"
Q_SUPERSEDE = (
    "MATCH (p:ActionProposal)-[:BASED_ON]->(a:Assessment) MATCH (m:Meta) "
    "WHERE p.status = 'proposed' AND a.state_version <> m.state_version SET p.status = 'superseded' RETURN count(p)"
)
Q_WRITE_ASSESSMENT = (
    "MERGE (a:Assessment {aid:$aid}) SET a += $p WITH a "
    "MATCH (l:Lift {uid:$lift}) MERGE (a)-[:ABOUT]->(l)"
)
Q_WRITE_FINDS = (
    "MATCH (a:Assessment {aid:$aid}) UNWIND $rows AS r MATCH (p:Node:Platform) WHERE p.stop_id = r.stop "
    "MERGE (a)-[f:FINDS {dir:r.dir}]->(p) SET f.k_before = r.kb, f.k_after = r.ka"
)
Q_WRITE_PROPOSAL = (
    "MATCH (a:Assessment {aid:$aid}) MERGE (p:ActionProposal {pid:$pid}) "
    "ON CREATE SET p += $p, p.created_at = $now MERGE (p)-[:BASED_ON]->(a) RETURN p.status"
)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Trace:
    """Events for one tick, in the agent event format (with the role in `agent` and W3C-style span ids)."""

    def __init__(self, scope):
        self.events, self.trace_id, self.scope = [], uuid.uuid4().hex, scope

    def emit(self, agent, event, **payload):
        ev = {"agent": agent, "type": event, "span_id": uuid.uuid4().hex[:16], "trace_id": self.trace_id, **payload}
        self.events.append(ev)
        return ev


def monitor(scope, trace):
    """The scope's lift closures: one item per (alert, facility)."""
    items = []
    for c in alerts.closures_for(scope):
        for fid in c["facility_ids"]:
            items.append({"facility_id": fid, "alert_id": c["alert_id"], "header": c.get("header")})
            trace.emit("monitor", "incident", facility_id=fid, alert_id=c["alert_id"])
    return items


def chronic_threshold(scope) -> int:
    g = db.client().select_graph(state.graph_name(scope))
    v = sorted(r[0] or 0 for r in g.ro_query(
        "MATCH (l:Node:Lift) WITH l.facility_id AS f, max(l.outages_12m) AS n RETURN n").result_set)
    return v[int(CHRONIC_QUANTILE * len(v))] if v else 10 ** 9


async def analyse(item, scope, trace, client, chronic_min=None):
    """Choose the playbook from graph facts, run its tools through MCP, write the Assessment."""
    graph = state.graph_name(scope)
    g = db.client().select_graph(graph)
    fid = item["facility_id"]
    version = (g.ro_query(Q_META_VERSION).result_set or [[None]])[0][0]
    facts = g.ro_query(Q_LIFT_FACTS, {"fid": fid}).result_set
    uid, modelled, cx, station, has_paths, outages = facts[0] if facts else (None, False, None, None, False, None)
    chronic = bool(outages and chronic_min is not None and outages >= chronic_min)
    calls = []

    async def call(name, args):
        res = await client.call_tool(name, {**args, **({"scope": scope} if name != "resolve_place" else {})},
                                     raise_on_error=False)
        env = res.structured_content or {}
        calls.append({"tool": name, "ok": env.get("ok"), "summary": env.get("summary")})
        trace.emit("analyst", "tool_result", tool=name, via="mcp", ok=env.get("ok"), summary=env.get("summary"))
        return env

    finds, targets = [], []
    if not uid or not modelled or not has_paths:
        playbook, verdict = "ABSTAIN", "CANNOT_ASSESS"
        await call("resolve_place", {"query": fid})
    else:
        stranded = g.ro_query(Q_ACCESS_LOST_BY, {"cx": cx, "fid": fid}).result_set
        new_last = g.ro_query(Q_NEW_LAST_AT, {"cx": cx}).result_set
        if stranded:
            playbook, verdict = "ACCESS_LOST", "LOSS"
            await call("platform_redundancy", {"station_id": station})
            for stop, _n, _pn, kbb, kb, keb, ke, lost_b, lost_e in stranded:
                label = " ".join(x for x in (_pn, _n) if x)
                if lost_b:
                    finds.append({"stop": stop, "dir": "board", "kb": kbb, "ka": kb, "name": label})
                    await call("step_free_route", {"from_station": station, "to_platform": stop})
                if lost_e:
                    finds.append({"stop": stop, "dir": "exit", "kb": keb, "ka": ke, "name": label})
                    await call("step_free_route", {"from_station": station, "from_platform": stop})
            await call("draft_action", {"facility_id": fid})
        elif new_last:
            playbook, verdict = "PREVENTIVE", "LAST_LIFT"
            targets = [r[0] for r in new_last]
            for t in targets:                       # re-check: closing the last lift too must cut access
                await call("what_if_close", {"facility_ids": [t]})
            await call("repair_priority", {})
        else:
            playbook, verdict = "NO_LOSS", "NO_LOSS"
            await call("platform_redundancy", {"station_id": station})
    aid = hashlib.sha1(f"{scope}|{fid}|{version}|{playbook}".encode()).hexdigest()[:16]
    props = {"run_id": trace.trace_id, "facility_id": fid, "station_id": station or "", "state_version": version,
             "playbook": playbook,
             "verdict": verdict, "chronic": chronic, "targets": targets, "alert_id": item["alert_id"],
             "created_at": _now(), "tools": [c["tool"] for c in calls]}
    if uid:
        g.query(Q_WRITE_ASSESSMENT, {"aid": aid, "p": props, "lift": uid})
        if finds:
            g.query(Q_WRITE_FINDS, {"aid": aid, "rows": [{k: f[k] for k in ("stop", "dir", "kb", "ka")} for f in finds]})
    trace.emit("analyst", "assessment", aid=aid, facility_id=fid, playbook=playbook, verdict=verdict,
               chronic=chronic, targets=targets, state_version=version)
    return {"aid": aid if uid else None, **props, "finds": finds}


def dispatch(assessment, scope, trace):
    """Proposals from the policy table, guarded by the current state_version. Returns the proposals made."""
    g = db.client().select_graph(state.graph_name(scope))
    g.query(Q_SUPERSEDE)
    aid = assessment.get("aid")
    if not aid or not g.ro_query(Q_GUARD, {"aid": aid}).result_set[0][0]:
        trace.emit("dispatcher", "guard", aid=aid, ok=False)
        return []
    trace.emit("dispatcher", "guard", aid=aid, ok=True)
    made = []
    fid, playbook = assessment["facility_id"], assessment["playbook"]
    for kind, rule in POLICY.items():
        if playbook not in rule["for"]:
            continue
        for target in (assessment["targets"] or [fid]) if kind == "protect_ticket" else [fid]:
            priority = "priority-1" if playbook == "ACCESS_LOST" or assessment["chronic"] else "priority-2"
            idem = f"lift-{target}:{playbook}:{kind}:{assessment['state_version']}"
            pid = hashlib.sha1(idem.encode()).hexdigest()[:16]
            status = "proposed" if rule["approval"] == "human" else "dry_run"
            res = g.query(Q_WRITE_PROPOSAL, {"aid": aid, "pid": pid, "now": _now(), "p": {
                "kind": kind, "status": status, "policy": rule["approval"], "idem_key": idem, "facility_id": target,
                "about": fid, "playbook": playbook, "label": priority, "scope": scope,
                "mode": settings.actions_mode}}).result_set
            made.append({"pid": pid, "kind": kind, "facility_id": target, "status": res[0][0] if res else status,
                         "label": priority})
            trace.emit("dispatcher", "proposal", pid=pid, kind=kind, facility_id=target, label=priority,
                       status=res[0][0] if res else status)
    return made


def notices(scope, assessments, trace, transport=None):
    """Rider notices (policy: auto): a loss notice per station with stranded platforms, a restore notice for a station
    whose last notice was a loss and which now has none."""
    from . import notify
    lost = {}
    for a in assessments:
        if a["playbook"] == "ACCESS_LOST" and a.get("station_id"):
            x = lost.setdefault(a["station_id"], {"lost": [], "lifts": []})
            x["lost"] += [{"platform": f["name"], "dir": f["dir"]} for f in a["finds"]]
            x["lifts"].append(a["facility_id"])
    out = []
    for sid, x in sorted(lost.items()):
        r = notify.publish(scope, sid, x["lost"], sorted(set(x["lifts"])), transport)
        out.append({"station_id": sid, **r})
        trace.emit("dispatcher", "rider_notice", station_id=sid, sent=r.get("sent"), reason=r.get("reason"),
                   kind=r.get("kind"))
    for sid, lifts in sorted(notify.open_losses(scope).items()):
        if sid not in lost:
            r = notify.publish(scope, sid, [], lifts, transport)
            out.append({"station_id": sid, **r})
            trace.emit("dispatcher", "rider_notice", station_id=sid, sent=r.get("sent"), reason=r.get("reason"),
                       kind=r.get("kind"))
    return out


async def tick(scope="live", transport=None):
    """Monitor -> Analyst -> Dispatcher for every current closure. Returns the trace and the outcome."""
    tools.prepare_scope(scope)
    trace = Trace(scope)
    items = monitor(scope, trace)
    chronic_min = chronic_threshold(scope)
    trace.emit("analyst", "policy", chronic_min_closures_12m=chronic_min)
    out = []
    async with Client(mcp) as client:
        for item in items:
            a = await analyse(item, scope, trace, client, chronic_min)
            out.append({**a, "proposals": dispatch(a, scope, trace)})
    sent = notices(scope, out, trace, transport)
    return {"scope": scope, "trace_id": trace.trace_id, "assessments": out, "notices": sent, "events": trace.events}


Q_INCIDENTS = (
    "MATCH (a:Assessment)-[:ABOUT]->(l:Lift) MATCH (m:Meta) "
    "OPTIONAL MATCH (a)-[f:FINDS]->(p:Platform) "
    "RETURN a.aid, a.facility_id, l.name, l.station_id, a.playbook, a.verdict, a.chronic, a.targets, a.state_version, "
    "a.state_version = m.state_version, a.created_at, collect(DISTINCT [p.stop_id, f.dir, f.k_before, f.k_after]) "
    "ORDER BY a.created_at DESC, a.facility_id"
)
Q_PROPOSALS = (
    "MATCH (p:ActionProposal)-[:BASED_ON]->(a:Assessment) WHERE $status IS NULL OR p.status = $status "
    "RETURN p.pid, p.kind, p.status, p.facility_id, p.about, p.playbook, p.label, p.policy, p.created_at, "
    "p.decided_at, p.approved_via, a.aid ORDER BY p.created_at DESC, p.pid"
)
Q_DECIDE = (
    "MATCH (p:ActionProposal {pid:$pid})-[:BASED_ON]->(a:Assessment) MATCH (m:Meta) "
    "RETURN p.status, p.approved_via, a.state_version = m.state_version, p.kind, p.facility_id, p.playbook, "
    "p.label, p.external_url"
)


def incidents(scope):
    g = db.client().select_graph(state.graph_name(scope))
    keys = ("aid", "facility_id", "name", "station_id", "playbook", "verdict", "chronic", "targets", "state_version",
            "current", "created_at")
    out = []
    for r in g.ro_query(Q_INCIDENTS).result_set:
        row = dict(zip(keys, r[:11]))
        row["finds"] = [{"stop_id": s, "dir": d, "k_before": kb, "k_after": ka} for s, d, kb, ka in r[11] if s]
        out.append(row)
    return out


def proposals(scope, status=None):
    g = db.client().select_graph(state.graph_name(scope))
    keys = ("pid", "kind", "status", "facility_id", "about", "playbook", "label", "policy", "created_at", "decided_at",
            "approved_via", "aid")
    return [dict(zip(keys, r)) for r in g.ro_query(Q_PROPOSALS, {"status": status}).result_set]


def decide(scope, pid, decision, idem_key, http=None):
    """A human decision on a proposal. Idempotent per key; refused if the assessment is no longer current."""
    g = db.client().select_graph(state.graph_name(scope))
    rs = g.ro_query(Q_DECIDE, {"pid": pid}).result_set
    if not rs:
        raise LookupError("no such proposal")
    status, via, current, kind, fid, playbook, label, url = rs[0]
    if via and via == idem_key:
        return {"pid": pid, "status": status, "repeat": True, **({"url": url} if url else {})}
    if status != "proposed":
        return {"pid": pid, "status": status, "error": f"proposal is {status}"}
    if not current:
        g.query("MATCH (p:ActionProposal {pid:$pid}) SET p.status = 'superseded'", {"pid": pid})
        return {"pid": pid, "status": "superseded", "error": "the graph changed since this was proposed"}
    new = {"approve": "approved_draft", "reject": "rejected"}[decision]
    out = {"pid": pid, "status": new, "kind": kind, "facility_id": fid}
    if new == "approved_draft" and kind in ("repair_ticket", "protect_ticket"):
        from . import tickets
        done = tickets.file(scope, {"facility_id": fid, "kind": kind, "playbook": playbook, "label": label}, http)
        out["draft"] = {**done["issue"], "filed": done["mode"] == "file"} if "issue" in done else None
        if done.get("url"):
            new = out["status"] = "executed"
            out["url"] = done["url"]
            out["action"] = done["action"]
            g.query("MATCH (p:ActionProposal {pid:$pid}) SET p.external_url = $u", {"pid": pid, "u": done["url"]})
    g.query("MATCH (p:ActionProposal {pid:$pid}) SET p.status = $s, p.approved_via = $k, p.decided_at = $t",
            {"pid": pid, "s": new, "k": idem_key, "t": _now()})
    return out
