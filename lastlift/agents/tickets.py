"""Approved repair / protect tickets as GitHub issues on the ops repository: a lift dossier with a Mermaid drawing of
the station's step-free graph. Files only when ACTIONS_MODE=file (the default, draft, returns the issue without
sending it). Dedupe: a hidden marker and a `lift-<id>` label; if an open issue for the lift exists, a comment is
added instead of a second issue. Each proposal files at most once (its external_url is kept on the proposal node).
"""
import re

import httpx

from .. import db, state, station_view, tools
from ..config import settings

API = "https://api.github.com"
MAX_NODES = 40


def _mid(x: str) -> str:
    return "n" + re.sub(r"[^A-Za-z0-9]", "_", x)


def mermaid(station_id: str, scope: str, lift: str, direction: str = "board") -> str:
    """flowchart TB of the contracted station graph (at most MAX_NODES nodes): closed lifts red, the newly last lift
    gold, the lift of this ticket emphasised."""
    view = station_view.view(station_id, direction, scope)
    nodes = view["nodes"][:MAX_NODES]
    keep = {n["id"] for n in nodes}
    edges = [e for e in view["edges"] if e["source"] in keep and e["target"] in keep]
    lines = ["flowchart TB"]
    for n in nodes:
        label = re.sub(r'["\[\]{}()<>|]', " ", n.get("label") or n["id"]).strip()[:40] or n["id"]
        lines.append(f'  {_mid(n["id"])}["{label}"]')
    red, gold = [], []
    for i, e in enumerate(edges):
        arrow = "-->" if e.get("step_free") else "-.->"
        lines.append(f"  {_mid(e['source'])} {arrow} {_mid(e['target'])}")
        if e.get("kind") == "lift" and e.get("status") == "closed":
            red.append(str(i))
    for n in nodes:
        if n.get("last_lift") and n.get("facility_id"):
            gold.append(_mid(n["id"]))
    lines.append("  classDef last fill:#f5b83d,stroke:#8a5300,stroke-width:3px")
    lines.append("  classDef this stroke:#0b5cad,stroke-width:4px")
    if gold:
        lines.append(f"  class {','.join(gold)} last")
    mine = [_mid(n["id"]) for n in nodes if n.get("facility_id") == lift]
    if mine:
        lines.append(f"  class {','.join(mine)} this")
    if red:
        lines.append(f"  linkStyle {','.join(red)} stroke:#d00,stroke-width:4px")
    return "\n".join(lines)


def issue(scope: str, proposal: dict) -> dict:
    fid = proposal["facility_id"]
    dossier = tools.lift_dossier(fid, scope)
    info = db.client().select_graph(state.graph_name(scope)).ro_query(
        "MATCH (l:Lift) WHERE l.facility_id = $f RETURN l.station_id, l.name LIMIT 1", {"f": fid}).result_set
    station, name = info[0] if info else ("", f"Elevator {fid}")
    kind = "Repair" if proposal["kind"] == "repair_ticket" else "Protect"
    key = f"lift-{fid}:{proposal.get('playbook', '')}"
    body = [f"<!-- lastlift:key={key} -->", (dossier.get("data") or {}).get("markdown", ""), ""]
    if station:
        body += ["## Station step-free graph", "", "```mermaid", mermaid(station, scope, fid), "```", "",
                 "Solid arrows are step-free; dotted are stairs or escalators. Red: closed lift. Gold: now the last lift."]
    body += ["", f"_Proposed by LastLift's Dispatcher ({proposal.get('playbook')}), approved by a human. Unofficial "
                 "decision support from the open-data model; check mbta.com/alerts/access._"]
    return {"title": f"[LastLift] {kind} lift {fid} ({name})", "body": "\n".join(body),
            "labels": ["lastlift", f"lift-{fid}", proposal.get("label") or "priority-2"], "key": key}


def file(scope: str, proposal: dict, http=None) -> dict:
    """Create the issue (or comment on the open one for this lift). Returns {mode, url?, action, issue}."""
    draft = issue(scope, proposal)
    if settings.actions_mode != "file":
        return {"mode": "draft", "action": "none", "issue": draft}
    if not settings.github_token:
        return {"mode": "draft", "action": "none", "issue": draft, "error": "no GitHub token configured"}
    h = {"Authorization": f"Bearer {settings.github_token}", "Accept": "application/vnd.github+json"}
    client = http or httpx.Client(timeout=20)
    label = f"lift-{proposal['facility_id']}"
    found = client.get(f"{API}/search/issues", headers=h,
                       params={"q": f"repo:{settings.ops_repo} is:issue is:open label:{label}"}).json()
    hit = next((i for i in found.get("items", []) if f"lastlift:key=lift-{proposal['facility_id']}" in (i.get("body") or "")),
               None)
    if hit:
        r = client.post(f"{hit['url']}/comments", headers=h,
                        json={"body": f"Still open per LastLift ({proposal.get('playbook')}).\n\n" + draft["body"]})
        return {"mode": "file", "action": "comment", "url": hit["html_url"], "status": r.status_code}
    r = client.post(f"{API}/repos/{settings.ops_repo}/issues", headers=h,
                    json={"title": draft["title"], "body": draft["body"], "labels": draft["labels"]})
    data = r.json()
    return {"mode": "file", "action": "create", "url": data.get("html_url"), "status": r.status_code}
