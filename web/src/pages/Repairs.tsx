import { useEffect, useRef, useState } from "react";
import { getEvalRows, getReroute, getState, getStations, getTicket, type Envelope } from "../api";
import { href } from "../router";
import { S } from "../strings.en";

export function Repairs() {
  const [state, setState] = useState<Awaited<ReturnType<typeof getState>> | null>(null);
  const [rows, setRows] = useState<Record<string, string>[]>([]);
  const [ticket, setTicket] = useState<Envelope | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [reroutes, setReroutes] = useState<{ platform: any; exit: Envelope; board: Envelope }[]>([]);
  const dlg = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    getState().then((s) => {
      setState(s);
      const lost = s.closures.data.platforms_lost as { stop_id: string }[];
      Promise.all(lost.map((p) => getReroute(p.stop_id).catch(() => null)))
        .then((rs) => setReroutes(rs.filter(Boolean) as any));
    }).catch(() => {});
    getEvalRows().then(setRows).catch(() => {});
    getStations().then((ss) => setNames(Object.fromEntries(ss.map((x) => [x.id, x.name])))).catch(() => {});
  }, []);

  async function openTicket(fid: string) {
    const t = await getTicket(fid).catch(() => null);
    if (t) { setTicket(t); dlg.current?.showModal(); }
  }

  if (!state) return <p aria-busy="true">…</p>;
  const ranked: any[] = state.priority.data.ranked;
  const ev = state.eval;
  return (
    <>
      <h1>{S.repairs.title}</h1>
      <p>{S.repairs.intro}</p>
      <div className="table-wrap">
        <table>
          <thead><tr>
            <th scope="col">{S.repairs.colTier}</th><th scope="col">{S.repairs.colLift}</th>
            <th scope="col">{S.repairs.colStation}</th><th scope="col">{S.repairs.colDirs}</th>
            <th scope="col">{S.repairs.colDeps}</th><th scope="col">{S.repairs.colPrior}</th><th scope="col"></th>
          </tr></thead>
          <tbody>
            {ranked.filter((r) => r.tier <= 2).concat(ranked.filter((r) => r.tier > 2).slice(0, 10)).map((r) => (
              <tr key={r.facility_id}>
                <td>{r.tier_label}</td>
                <th scope="row">{r.facility_id} <span className="muted">{r.name}</span></th>
                <td><a href={href(`/station/${r.station_id}`)}>{names[r.station_id] ?? r.station_id}</a></td>
                <td>{r.platform_directions}</td>
                <td>{r.departures_day}</td>
                <td>{r.incidents}</td>
                <td>{r.tier <= 2 && <button onClick={() => openTicket(r.facility_id)}>{S.repairs.draft}</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <dialog ref={dlg} aria-labelledby="tk-h">
        <h2 id="tk-h">{S.repairs.ticketTitle}</h2>
        {ticket && <>
          <p><strong>{ticket.data.title}</strong></p>
          <pre className="cypher">{ticket.data.body}</pre>
        </>}
        <form method="dialog"><button>{S.agent.close}</button></form>
      </dialog>

      <h2>{S.repairs.reroute}</h2>
      {reroutes.map((r) => (
        <section key={r.platform.stop_id} className="panel" style={{ marginBottom: "1rem" }}>
          <h3>{r.platform.name} {r.platform.platform_name}</h3>
          <p><strong>{S.repairs.rerouteExit}:</strong> {r.exit.summary}</p>
          <ol>{(r.exit.data.routes?.[0]?.steps ?? []).map((s: any, i: number) => <li key={i}>{s.text}</li>)}</ol>
          <p><strong>{S.repairs.rerouteBoard}:</strong> {r.board.summary}</p>
          <ol>{(r.board.data.routes?.[0]?.steps ?? []).map((s: any, i: number) => <li key={i}>{s.text}</li>)}</ol>
        </section>
      ))}

      <h2>{S.repairs.officialTitle}</h2>
      <p>{S.repairs.officialIntro}</p>
      {ev.live_scored !== undefined && <>
        <p><strong>{S.repairs.scored(ev.live_agree, ev.live_partial, ev.live_disagree, ev.live_scored)}</strong></p>
        <p>{S.repairs.falseAccessible(ev.live_false_accessible, (ev.live_false_accessible_cases ?? []).join(", "))}</p>
      </>}
      <div className="table-wrap">
        <table>
          <thead><tr><th scope="col">{S.repairs.colAlert}</th><th scope="col">{S.repairs.colMbta}</th>
            <th scope="col">{S.repairs.colModel}</th><th scope="col">{S.repairs.colMatch}</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.gold_id}>
                <th scope="row">{r.gold_id} · {r.facility_ids}</th>
                <td>{r.exp_verdict} <span className="muted">{r.labeller_notes}</span></td>
                <td>{r.model_verdict}</td>
                <td>{r.match}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
