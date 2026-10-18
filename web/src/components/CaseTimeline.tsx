import { useEffect, useState } from "react";
import { getFiled, type Filed } from "../api";
import { href } from "../router";
import { S } from "../strings.en";

/** One closure followed end to end, from data: the Monitor's incident, the Analyst's playbook from the graph, the
 *  Dispatcher's guarded proposal, a person's approval, and the GitHub issue it filed (web/public/m/filed.json). */
export function CaseTimeline({ ops, names }: { ops: Record<string, any>; names: Record<string, string> }) {
  const [filed, setFiled] = useState<Filed | null>(null);
  useEffect(() => { getFiled().then(setFiled).catch(() => {}); }, []);
  if (!filed?.issues.length) return null;

  // the first filed ticket whose proposal came from an assessment in the mirrored run
  const pick = filed.issues.map((i) => {
    const a = (ops.assessments ?? []).find((x: any) => (x.proposals ?? []).some((p: any) => p.facility_id === i.facility_id && p.kind === i.kind));
    return a ? { issue: i, a } : null;
  }).find(Boolean);
  if (!pick) return null;
  const { issue, a } = pick;
  const station = names[a.station_id] ?? a.station_id;
  const kind = issue.kind === "protect_ticket" ? S.timeline.protect : S.timeline.repair;
  const guard = (ops.events ?? []).find((e: any) => e.type === "guard");
  const steps: { who: string; what: string; tone: string }[] = [
    { who: S.ops.stage.monitor, what: S.timeline.monitor(a.facility_id, station), tone: "monitor" },
    { who: S.ops.stage.analyst, what: S.timeline.analyst(S.ops.playbook[a.playbook as keyof typeof S.ops.playbook] ?? a.playbook,
      (a.targets ?? []).join(", ") || issue.facility_id), tone: "analyst" },
    { who: S.ops.stage.dispatcher, what: S.timeline.dispatcher(kind, issue.facility_id, !!guard), tone: "dispatcher" },
    { who: S.ops.stage.human, what: S.timeline.human, tone: "human" },
  ];
  return (
    <section className="tl card section-gap" aria-labelledby="tl-h">
      <h2 id="tl-h">{S.timeline.title}</h2>
      <p className="muted">{S.timeline.lead(station)}</p>
      <ol className="tl-steps">
        {steps.map((s, i) => (
          <li key={i} data-tone={s.tone}><span className="tl-who">{s.who}</span><span className="tl-what">{s.what}</span></li>
        ))}
        <li data-tone="filed">
          <span className="tl-who">{S.timeline.github}</span>
          <span className="tl-what"><a href={issue.url} target="_blank" rel="noreferrer">{S.timeline.issue(issue.number, filed.repo)}</a>
            {" "}<span className="muted">{new Date(issue.filed_at).toUTCString().replace(" GMT", " UTC")}</span></span>
        </li>
      </ol>
      <p className="tl-foot">
        <a href={filed.issues_url} target="_blank" rel="noreferrer">{S.timeline.all(filed.issues.length)}</a>
        {" · "}<a href={href(`/station/${a.station_id}`)}>{S.timeline.station(station)}</a>
      </p>
    </section>
  );
}
