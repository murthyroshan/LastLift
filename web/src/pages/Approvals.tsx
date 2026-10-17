import { useEffect, useState } from "react";
import { getOps, decideProposal, getProposals, getStations, type Scope } from "../api";
import { href } from "../router";
import { S } from "../strings.en";

/** The operations agents' work: what each closure means (Analyst) and the actions it proposes (Dispatcher), with the
 *  human decision. The snapshot comes from the mirror; decisions need the live API. */
export function Approvals({ scope, live }: { scope: Scope; live: boolean }) {
  const [ops, setOps] = useState<Record<string, any> | null>(null);
  const [inbox, setInbox] = useState<any[] | null>(null);
  const [msg, setMsg] = useState("");
  const [names, setNames] = useState<Record<string, string>>({});
  useEffect(() => {
    getOps().then(setOps).catch(() => {});
    getStations().then((ss) => setNames(Object.fromEntries(ss.map((x) => [x.id, x.name])))).catch(() => {});
    if (live) getProposals(scope).then(setInbox).catch(() => setInbox(null));
  }, [scope, live]);

  async function decide(pid: string, decision: "approve" | "reject") {
    const r = await decideProposal(scope, pid, decision).catch(() => null);
    setMsg(r ? S.ops.decided(pid, r.status) : S.ops.failed);
    getProposals(scope).then(setInbox).catch(() => {});
  }

  if (!ops) return <p aria-busy="true">…</p>;
  const rows: any[] = ops.assessments.filter((a: any) => a.playbook !== "ABSTAIN");
  const proposals = ops.assessments.flatMap((a: any) => a.proposals ?? []);
  const incidents = (ops.events ?? []).filter((e: any) => e.type === "incident").length;
  const toolCalls = (ops.events ?? []).filter((e: any) => e.type === "tool_result").length;
  const guards = (ops.events ?? []).filter((e: any) => e.type === "guard");
  return (
    <>
      <p className="eyebrow">{S.ops.eyebrow}</p>
      <h1>{S.ops.title}</h1>
      <p className="lead">{S.ops.intro}</p>
      <ol className="pipeline" aria-label={S.ops.pipeline}>
        <li data-agent="monitor"><span className="pl-n">{incidents}</span><span className="pl-t">{S.ops.stage.monitor}</span>
          <span className="pl-d">{S.ops.stageText.monitor}</span></li>
        <li data-agent="analyst"><span className="pl-n">{rows.length}</span><span className="pl-t">{S.ops.stage.analyst}</span>
          <span className="pl-d">{S.ops.stageText.analyst(toolCalls)}</span></li>
        <li data-agent="dispatcher"><span className="pl-n">{proposals.length}</span><span className="pl-t">{S.ops.stage.dispatcher}</span>
          <span className="pl-d">{S.ops.stageText.dispatcher(guards.filter((g: any) => g.ok).length, guards.length)}</span></li>
        <li data-agent="human"><span className="pl-n">{live && inbox ? inbox.length : "–"}</span><span className="pl-t">{S.ops.stage.human}</span>
          <span className="pl-d">{S.ops.stageText.human}</span></li>
      </ol>

      <section aria-labelledby="as-h">
        <h2 id="as-h">{S.ops.assessTitle}</h2>
        <ul className="cases">
          {rows.map((a) => (
            <li key={a.facility_id} className="case" data-playbook={a.playbook}>
              <div className="case-top">
                <span className="mono case-fid">{a.facility_id}</span>
                {a.station_id && <a href={href(`/station/${a.station_id}`)}>{names[a.station_id] ?? a.station_id}</a>}
                {a.chronic && <span className="pill" data-k="1">{S.ops.chronic}</span>}
              </div>
              <p className="case-playbook">{S.ops.playbook[a.playbook as keyof typeof S.ops.playbook] ?? a.playbook}</p>
              <p className="case-finds">{(a.finds ?? []).map((f: any) => `${f.name} (${f.dir})`).join("; ") ||
                (a.targets?.length ? S.ops.protects(a.targets.join(", ")) : "–")}</p>
              {(a.proposals ?? []).length > 0 && <ul className="case-props">
                {a.proposals.map((p: any) => <li key={p.pid}><span className="pill" data-k="sim">
                  {S.ops.kind[p.kind as keyof typeof S.ops.kind] ?? p.kind} {p.facility_id}</span></li>)}
              </ul>}
            </li>
          ))}
        </ul>
        <p className="muted">{S.ops.abstained(ops.assessments.length - rows.length)}</p>
      </section>

      <section aria-labelledby="in-h" className="card section-gap">
        <h2 id="in-h">{S.ops.inboxTitle}</h2>
        {!live || !inbox ? <p>{S.ops.needsLive}</p> : inbox.length === 0 ? <p>{S.ops.empty}</p> : (
          <ul>
            {inbox.map((p) => (
              <li key={p.pid}>
                {S.ops.kind[p.kind as keyof typeof S.ops.kind] ?? p.kind} {p.facility_id} ({p.label}){" "}
                <button onClick={() => decide(p.pid, "approve")}>{S.ops.approve}</button>{" "}
                <button onClick={() => decide(p.pid, "reject")}>{S.ops.reject}</button>
              </li>
            ))}
          </ul>
        )}
        {msg && <p role="status">{msg}</p>}
        <p className="muted">{S.ops.policy}</p>
      </section>

      {ops.notices?.length > 0 && <section aria-labelledby="no-h">
        <h2 id="no-h">{S.ops.noticesTitle}</h2>
        <ul>{ops.notices.map((n: any) => <li key={n.station_id}><strong>{n.title}</strong>: {n.body}</li>)}</ul>
        <p className="muted">{S.ops.noticesNote}</p>
      </section>}
    </>
  );
}
