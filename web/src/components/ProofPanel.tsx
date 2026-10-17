import { useEffect, useId, useState } from "react";
import { getCuts, getHistory, reliability, type CutsBundle } from "../api";
import { S } from "../strings.en";

const pct = (x: number) => (x * 100 < 0.01 && x > 0 ? (x * 100).toExponential(1) : (x * 100).toFixed(2));

/** For one platform-direction: every minimum cut, the exact reliability for a chosen per-lift outage chance,
 *  and what each single lift closure does. All of it comes from the network sweep (the mirror). */
export function ProofPanel({ stationId, stop, dir, name }: {
  stationId: string; stop: string | null; dir: "board" | "exit"; name: string;
}) {
  const [cuts, setCuts] = useState<CutsBundle | null>(null);
  const [q, setQ] = useState<number | null>(null);
  const [emp, setEmp] = useState<Record<string, number>>({});
  const sliderId = useId();
  useEffect(() => { getCuts(stationId).then(setCuts).catch(() => setCuts(null)); }, [stationId]);
  useEffect(() => { getHistory(stationId).then((h) => setEmp(h.empirical ?? {})).catch(() => setEmp({})); }, [stationId]);
  useEffect(() => { if (cuts && q === null) setQ(cuts.q_assumed); }, [cuts, q]);

  if (!stop) return <section aria-labelledby="pf-h"><h2 id="pf-h">{S.proof.title}</h2><p>{S.proof.pick}</p></section>;
  const d = cuts?.platforms[stop]?.[dir];
  if (!cuts || !d) return null;
  const qq = q ?? cuts.q_assumed;
  return (
    <section aria-labelledby="pf-h" className="panel">
      <h2 id="pf-h">{S.proof.title}: {name}, {S.proof.dirLabel(dir)}</h2>
      {d.at_grade ? <p>{S.proof.atGrade}</p> : d.k === 0 ? <p>{S.proof.lost}</p> : d.mincuts && <>
        <p>{S.proof.cutsLead(d.k ?? 0, d.mincuts.length === 1)}</p>
        <ul className="cuts">
          {d.mincuts.map((c) => <li key={c.join("+")}><strong>{c.join(" + ")}</strong></li>)}
        </ul>
        {d.mincuts.length === 1 && <p>{S.proof.cutsOnly}</p>}
        <p className="muted">{S.proof.certified}</p>
      </>}

      {d.rel_counts && <>
        <h3>{S.proof.relTitle}</h3>
        <label htmlFor={sliderId}>{S.proof.relLabel}: <strong>{(qq * 100).toFixed(1)}%</strong></label><br />
        <input id={sliderId} type="range" min={0.001} max={0.2} step={0.001} value={qq}
               onChange={(e) => setQ(Number(e.target.value))} style={{ width: "min(100%, 22rem)" }} />
        {(() => {
          const r = reliability(d.rel_counts!, qq);
          return <p aria-live="polite">{r > 0 ? S.proof.relResult(pct(r), (-Math.log10(r)).toFixed(1)) : S.proof.relNever}</p>;
        })()}
        <p className="muted">{S.proof.relNote((cuts.q_assumed * 100).toFixed(0))}</p>
        {emp[`${stop}:${dir}`] !== undefined && <p>{S.proof.empirical(pct(emp[`${stop}:${dir}`]))}</p>}
      </>}

      {d.k !== null && d.k > 0 && <>
        <h3>{S.proof.n1Title}</h3>
        {Object.keys(d.k_without ?? {}).length === 0 ? <p>{S.proof.n1None}</p> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th scope="col">{S.proof.colLift}</th><th scope="col">{S.proof.colLeft}</th></tr></thead>
              <tbody>
                {Object.entries(d.k_without ?? {}).map(([f, k]) => (
                  <tr key={f}><th scope="row">{f}</th><td>{k}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </>}
    </section>
  );
}
