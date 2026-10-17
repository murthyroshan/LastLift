import { useEffect, useRef, useState } from "react";
import { getContingency, getEvalRows, getLiftRecords, getRerouteFor, getStateFor, getStations, getTicketFor, type Envelope, type Scope } from "../api";
import { href } from "../router";
import { S } from "../strings.en";

export function Repairs({ scope }: { scope: Scope }) {
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
  return (
    <>
      <h1>{S.repairs.title}</h1>
      <p>{S.repairs.intro}</p>
      <div className="table-wrap">
        <table>
          <thead><tr>
            <th scope="col">{S.repairs.colTier}</th><th scope="col">{S.repairs.colLift}</th>
            <th scope="col">{S.repairs.colStation}</th><th scope="col">{S.repairs.colDirs}</th>
            <th scope="col">{S.repairs.colDeps}</th><th scope="col">{S.repairs.colPrior}</th>
            <th scope="col">{S.repairs.colChronic}</th><th scope="col"></th>
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
                <td>{records[r.facility_id]?.outages_12m ?? "–"}</td>
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

      {order && order.data?.order?.length > 0 && <section aria-labelledby="or-h">
        <h2 id="or-h">{S.order.title}</h2>
        <p>{S.order.intro}</p>
        <ol>{order.data.order.map((x: any) => (
          <li key={x.facility_id}>{S.order.step(x.facility_id, x.journeys_restored, x.platform_directions_restored)}</li>
        ))}</ol>
        {order.data.exact && <p className="muted">{S.order.exact}{" "}
          {order.data.gap?.[0] === 0 && order.data.gap?.[1] === 0 ? S.order.greedySame : S.order.greedyDiffers}</p>}
      </section>}

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
