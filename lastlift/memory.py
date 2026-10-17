"""Memory and provenance in the graph: every agent run, what it read, and whether its answer is still true.

  (:Run {run_id, client, model, tokens_in, tokens_out, ms, state_version, at})
     -[:CALLED {seq}]->(:ToolCall {tid, tool, args_sha, ok, query_ids})-[:READ]->(:Lift | :Platform | :Station)
  (:Answer {run_id, source, grounded, stale, stale_reason, question})-[:CITES]->(:ToolCall)
  (:Disagreement {facility_id, mbta, model, source})-[:ON]->(:Lift)    MBTA's advice differed from the model

Self-invalidation: when a lift changes state (state.sync), every answer that read it is marked stale in the same
step; an unrelated answer is untouched. "Memory" here means observed history, assessments, disagreements and
provenance; nothing is learned. Runtime records are kept in the scope graph (at most MAX_RUNS runs) and are rebuilt
empty on a new deployment; Disagreements are seeded from the committed validation (data/memory/disagreements.json).
"""
import hashlib
import json
import time
import uuid

from . import db
from .config import REPO_ROOT

MAX_RUNS = 500
DISAGREEMENTS = REPO_ROOT / "data" / "memory" / "disagreements.json"

Q_RUN = (
    "CREATE (r:Run) SET r = $run WITH r UNWIND $calls AS c CREATE (t:ToolCall) SET t = c.p "
    "CREATE (r)-[:CALLED {seq:c.seq}]->(t)"
)
Q_READS = (
    "UNWIND $rows AS row MATCH (t:ToolCall {tid:row.tid}) "
    "OPTIONAL MATCH (l:Lift) WHERE l.facility_id IN row.ents "
    "OPTIONAL MATCH (p:Node:Platform) WHERE p.stop_id IN row.ents "
    "OPTIONAL MATCH (s:Station) WHERE s.uid IN row.ents "
    "WITH t, collect(DISTINCT l) + collect(DISTINCT p) + collect(DISTINCT s) AS targets "
    "UNWIND targets AS x WITH t, x WHERE x IS NOT NULL MERGE (t)-[:READ]->(x)"
)
Q_ANSWER = (
    "CREATE (a:Answer) SET a = $a WITH a MATCH (t:ToolCall) WHERE t.tid IN $tids MERGE (a)-[:CITES]->(t)"
)
Q_INVALIDATE = (
    "MATCH (l:Lift)<-[:READ]-(:ToolCall)<-[:CITES]-(a:Answer) WHERE l.facility_id IN $changed AND a.stale = false "
    "SET a.stale = true, a.stale_reason = 'lift ' + l.facility_id + ' changed state' RETURN count(DISTINCT a)"
)
Q_PRUNE = (
    "MATCH (r:Run) WITH r ORDER BY r.at DESC SKIP $keep "
    "OPTIONAL MATCH (r)-[:CALLED]->(t:ToolCall) OPTIONAL MATCH (a:Answer {run_id:r.run_id}) DETACH DELETE r, t, a"
)
Q_CLEAR_DISAGREE = "MATCH (d:Disagreement) DETACH DELETE d"
Q_DISAGREE = (
    "UNWIND $rows AS r MATCH (l:Lift) WHERE l.facility_id = r.facility_id WITH r, min(l.uid) AS lu "
    "MATCH (l:Lift {uid:lu}) CREATE (d:Disagreement) SET d = r CREATE (d)-[:ON]->(l)"
)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def record_run(graph: str, client: str, question: str | None, events: list[dict], results: list[dict],
               answer: dict | None, state_version: str | None) -> str:
    """Write one run (best effort: a failure here never changes an answer)."""
    run_id = uuid.uuid4().hex[:16]
    calls = [e for e in events if e.get("type") == "tool_call"]
    rows, reads = [], []
    for seq, (c, res) in enumerate(zip(calls, results), 1):
        tid = f"{run_id}:{seq}"
        rows.append({"seq": seq, "p": {"tid": tid, "tool": c["tool"], "ok": bool(res.get("ok")),
                                       "args_sha": hashlib.sha256(json.dumps(c.get("args", {}), sort_keys=True)
                                                                  .encode()).hexdigest()[:16],
                                       "query_ids": (res.get("evidence") or {}).get("query_ids", [])}})
        reads.append({"tid": tid, "ents": [str(x) for x in res.get("entities", [])]})
    usage = (answer or {}).get("usage") or {}
    run = {"run_id": run_id, "client": client, "model": (answer or {}).get("model") or "",
           "tokens_in": usage.get("input_tokens") or 0, "tokens_out": usage.get("output_tokens") or 0,
           "state_version": state_version or "", "at": _now(), "tools": len(rows)}
    g = db.client().select_graph(graph)
    g.query(Q_RUN, {"run": run, "calls": rows})
    if reads:
        g.query(Q_READS, {"rows": reads})
    if answer is not None:
        g.query(Q_ANSWER, {"a": {"run_id": run_id, "source": answer.get("source", ""),
                                 "grounded": bool(answer.get("grounded", True)), "stale": False, "stale_reason": "",
                                 "question": (question or "")[:300], "at": run["at"]},
                           "tids": [r["p"]["tid"] for r in rows]})
    g.query(Q_PRUNE, {"keep": MAX_RUNS})
    return run_id


def invalidate(graph: str, changed) -> int:
    if not changed:
        return 0
    rs = db.client().select_graph(graph).query(Q_INVALIDATE, {"changed": sorted(changed)}).result_set
    return rs[0][0] if rs else 0


def sync_disagreements(graph: str) -> int:
    rows = json.loads(DISAGREEMENTS.read_text(encoding="utf-8")) if DISAGREEMENTS.is_file() else []
    g = db.client().select_graph(graph)
    g.query(Q_CLEAR_DISAGREE)
    if rows:
        g.query(Q_DISAGREE, {"rows": rows})
    return len(rows)


Q_RECALL = {
    "assessments": "MATCH (a:Assessment)-[:ABOUT]->(l:Lift) WHERE l.facility_id = $fid "
                   "RETURN a.created_at, a.playbook, a.verdict, a.state_version ORDER BY a.created_at DESC LIMIT 10",
    "proposals": "MATCH (p:ActionProposal) WHERE p.facility_id = $fid OR p.about = $fid "
                 "RETURN p.kind, p.status, p.label, p.created_at ORDER BY p.created_at DESC LIMIT 10",
    "disagreements": "MATCH (d:Disagreement)-[:ON]->(l:Lift) WHERE l.facility_id = $fid "
                     "RETURN d.mbta, d.model, d.source",
    "answers": "MATCH (a:Answer)-[:CITES]->(:ToolCall)-[:READ]->(l:Lift) WHERE l.facility_id = $fid "
               "RETURN count(DISTINCT a), sum(CASE WHEN a.stale THEN 1 ELSE 0 END)",
}


def recall(graph: str, fid: str) -> dict:
    g = db.client().select_graph(graph)
    out = {k: g.ro_query(q, {"fid": fid}).result_set for k, q in Q_RECALL.items()}
    n, stale = (out["answers"][0] if out["answers"] else (0, 0))
    return {"assessments": [dict(zip(("at", "playbook", "verdict", "state_version"), r)) for r in out["assessments"]],
            "proposals": [dict(zip(("kind", "status", "label", "at"), r)) for r in out["proposals"]],
            "disagreements": [dict(zip(("mbta", "model", "source"), r)) for r in out["disagreements"]],
            "answers_citing": n or 0, "answers_stale": stale or 0}
