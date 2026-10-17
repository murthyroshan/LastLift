import { useEffect, useState } from "react";
import { getHistory, type HistoryBundle } from "../api";
import { S } from "../strings.en";

/** The Lift Ledger for one station: reported closures replayed through today's layout. Frequencies only. */
export function HistoryPanel({ stationId, platformName }: {
  stationId: string; platformName: (stop: string) => string;
}) {
  const [h, setH] = useState<HistoryBundle | null>(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    setH(null); setMissing(false);
    getHistory(stationId).then(setH).catch(() => setMissing(true));
  }, [stationId]);
  if (!h && !missing) return null;
  const rows = h ? Object.entries(h.platforms).sort((a, b) => b[1].svc_h - a[1].svc_h) : [];
  const lifts = h ? Object.entries(h.lifts).sort((a, b) => a[0].localeCompare(b[0])) : [];
  return (
    <section aria-labelledby="hi-h">
      <h2 id="hi-h">{S.hist.title}</h2>
      {h && <p className="muted">{S.hist.intro(h.from, h.to)}</p>}
      {rows.length === 0 ? <p>{S.hist.none}</p> : (
        <ul>
          {rows.map(([key, x]) => {
            const [stop, dir] = key.split(":");
            return <li key={key}>{S.hist.platformLine(platformName(stop), S.proof.dirLabel(dir).toLowerCase(),
              Math.round(x.svc_h), x.months)}</li>;
          })}
        </ul>
      )}
      {lifts.length > 0 && <>
        <h3>{S.hist.liftsTitle}</h3>
        <div className="table-wrap" tabIndex={0}>
          <table>
            <thead><tr>
              <th scope="col">{S.hist.colLift}</th><th scope="col">{S.hist.colAvail}</th>
              <th scope="col">{S.hist.colClosures}</th><th scope="col">{S.hist.colMedian}</th>
              <th scope="col">{S.hist.colCost}</th>
            </tr></thead>
            <tbody>
              {lifts.map(([f, x]) => (
                <tr key={f}>
                  <th scope="row">{f}</th>
                  <td>{x.avail_12m !== undefined ? `${(x.avail_12m * 100).toFixed(1)}%` : "–"}</td>
                  <td>{x.outages_12m ?? "–"}</td>
                  <td>{x.mttr_h ?? "–"}</td>
                  <td>{Math.round(x.single_svc_h ?? 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {lifts.filter(([, x]) => x.months && Object.keys(x.months).length).map(([f, x]) => (
          <details key={f}>
            <summary>{S.hist.showMonths(f)}</summary>
            <Strip months={x.months!} label={S.hist.stripLabel(f)} />
            <div className="table-wrap" tabIndex={0}>
              <table>
                <thead><tr><th scope="col">{S.hist.colMonth}</th><th scope="col">{S.hist.colHours}</th></tr></thead>
                <tbody>{Object.entries(x.months!).map(([m, v]) => (
                  <tr key={m}><th scope="row">{m}</th><td>{v}</td></tr>
                ))}</tbody>
              </table>
            </div>
          </details>
        ))}
      </>}
    </section>
  );
}

/** One cell per month, shaded by hours closed; decorative (the table under it carries the numbers). */
function Strip({ months, label }: { months: Record<string, number>; label: string }) {
  const keys = Object.keys(months).sort();
  const max = Math.max(...Object.values(months), 1);
  return (
    <div className="strip" aria-hidden="true" title={label}>
      {keys.map((m) => (
        <span key={m} style={{ opacity: 0.15 + 0.85 * (months[m] / max) }} />
      ))}
    </div>
  );
}
