import { useEffect, useRef, useState } from "react";
import { getContingency, getEvalRows, getLiftRecords, getRerouteFor, getStateFor, getStations, getTicketFor, type Envelope, type Scope } from "../api";
import { OneLift } from "../components/OneLift";
import { WorstDay } from "../components/WorstDay";
import { href } from "../router";
import { S } from "../strings.en";

export function Repairs({ scope, live = false }: { scope: Scope; live?: boolean }) {
  const [state, setState] = useState<Awaited<ReturnType<typeof getStateFor>> | null>(null);
  const [rows, setRows] = useState<Record<string, string>[]>([]);
  const [ticket, setTicket] = useState<Envelope | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [reroutes, setReroutes] = useState<{ platform: any; exit: Envelope; board: Envelope }[]>([]);
  const [order, setOrder] = useState<Envelope | null>(null);
  const [records, setRecords] = useState<Record<string, any>>({});
  const dlg = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    getStateFor(scope).then((s) => {
      setState(s);
      const lost = s.closures.data.platforms_lost as { stop_id: string; station_id: string }[];
      Promise.all(lost.map((p) => getRerouteFor(p, scope).catch(() => null)))
        .then((rs) => setReroutes(rs.filter(Boolean) as any));
    }).catch(() => {});
    getEvalRows().then(setRows).catch(() => {});
    getContingency(scope).then((c) => setOrder(c.order)).catch(() => {});
    getLiftRecords().then((r) => setRecords(r.lifts)).catch(() => {});
    getStations().then((ss) => setNames(Object.fromEntries(ss.map((x) => [x.id, x.name])))).catch(() => {});
  }, [scope]);

  async function openTicket(fid: string) {
    const t = await getTicketFor(fid, scope).catch(() => null);
    if (t) { setTicket(t); dlg.current?.showModal(); }
  }

  if (!state) return <p aria-busy="true">…</p>;
  const ranked: any[] = state.priority.data.ranked;
  const ev = state.eval;
  const shownRanks = ranked.filter((r) => r.tier <= 2).concat(ranked.filter((r) => r.tier > 2).slice(0, 10));
  const maxDirs = Math.max(1, ...shownRanks.map((r) => r.platform_directions ?? 0));
  const maxDeps = Math.max(1, ...shownRanks.map((r) => r.departures_day ?? 0));
  const maxOut = Math.max(1, ...shownRanks.map((r) => records[r.facility_id]?.outages_12m ?? 0));
  const pct = (v: number, max: number) => Math.round((100 * (v ?? 0)) / max);
  return (
    <>
      <p className="eyebrow">{S.repairs.eyebrow}</p>
      <h1>{S.repairs.title}</h1>
      <p className="lead">{S.repairs.intro}</p>
      <ol className="rank-list">
        {shownRanks.map((r, i) => (
          <li key={`${r.facility_id}-${i}`} className="rank-card" data-tier={r.tier <= 1 ? "now" : r.tier <= 2 ? "protect" : "watch"}>
            <span className="rank-no" aria-hidden="true">{i + 1}</span>
            <div className="rank-main">
              <p className="tier-line"><span className="tier" data-tier={r.tier <= 1 ? "repair_now" : r.tier <= 2 ? "protect" : "watch"}>{r.tier_label}</span></p>
              <h2 className="rank-title"><span className="mono">{r.facility_id}</span> <span className="muted">{r.name}</span></h2>
              <p className="rank-station"><a href={href(`/station/${r.station_id}`)}>{names[r.station_id] ?? r.station_id}</a></p>
            </div>
            <dl className="rank-metrics">
              <div><dt>{S.repairs.colDirs}</dt><dd>{r.platform_directions}
                <span className="bar" data-k="0" aria-hidden="true"><span style={{ width: `${pct(r.platform_directions, maxDirs)}%` }} /></span></dd></div>
              <div><dt>{S.repairs.colDeps}</dt><dd>{r.departures_day}
                <span className="bar" data-k="2" aria-hidden="true"><span style={{ width: `${pct(r.departures_day, maxDeps)}%` }} /></span></dd></div>
              <div><dt>{S.repairs.colPrior}</dt><dd>{r.incidents}</dd></div>
              <div><dt>{S.repairs.colChronic}</dt><dd>{records[r.facility_id]?.outages_12m ?? "–"}
                <span className="bar" aria-hidden="true"><span style={{ width: `${pct(records[r.facility_id]?.outages_12m ?? 0, maxOut)}%` }} /></span></dd></div>
            </dl>
            <div className="rank-act">
              {r.tier <= 2 && <button onClick={() => openTicket(r.facility_id)}>{S.repairs.draft}</button>}
            </div>
          </li>
        ))}
      </ol>

      <dialog ref={dlg} aria-labelledby="tk-h">
        <h2 id="tk-h">{S.repairs.ticketTitle}</h2>
        {ticket && <>
          <p><strong>{ticket.data.title}</strong></p>
          <pre className="cypher">{ticket.data.body}</pre>
        </>}
        <form method="dialog"><button>{S.agent.close}</button></form>
      </dialog>

      {order && order.data?.order?.length > 0 && <section aria-labelledby="or-h">
        <h2 id="or-h">{S.order.title}</h2>
        <p>{S.order.intro}</p>
        <ol>{order.data.order.map((x: any) => (
          <li key={x.facility_id}>{S.order.step(x.facility_id, x.journeys_restored, x.platform_directions_restored)}</li>
        ))}</ol>
        {order.data.exact && <p className="muted">{S.order.exact}{" "}
          {order.data.gap?.[0] === 0 && order.data.gap?.[1] === 0 ? S.order.greedySame : S.order.greedyDiffers}</p>}
      </section>}

      <WorstDay live={live} />
      <OneLift />

      <h2 className="section-gap">{S.repairs.reroute}</h2>
      {reroutes.map((r) => (
        <section key={r.platform.stop_id} className="card" style={{ marginBottom: "1rem" }}>
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
      <div className="table-wrap" tabIndex={0}>
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
