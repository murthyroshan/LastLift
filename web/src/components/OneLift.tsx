import { useEffect, useState } from "react";
import { getOneLift } from "../api";
import { S } from "../strings.en";

type Row = { eid: string; pathway_ids: string[]; kind: string; station: string; hours_2025: number; k_gains_baseline: number };

/** Where one new lift would have prevented the most 2025 hours without a step-free route (exact pricing). Parallel
 *  runs at one station with the same effect are shown as one row. */
export function OneLift() {
  const [doc, setDoc] = useState<{ top: Row[]; top_by_baseline_gain: Row[]; year: number; exactness_checked: number } | null>(null);
  useEffect(() => { getOneLift().then(setDoc).catch(() => {}); }, []);
  if (!doc) return null;
  const groups: { station: string; hours: number; gain: number; kind: string; ids: string[] }[] = [];
  for (const r of doc.top) {
    const g = groups.find((x) => x.station === r.station && x.hours === r.hours_2025);
    if (g) g.ids.push(...r.pathway_ids.slice(0, 1));
    else groups.push({ station: r.station, hours: r.hours_2025, gain: r.k_gains_baseline, kind: r.kind,
                       ids: r.pathway_ids.slice(0, 1) });
  }
  const naive = doc.top_by_baseline_gain[0];
  return (
    <section aria-labelledby="ol-h">
      <h2 id="ol-h">{S.onelift.title}</h2>
      <p>{S.onelift.intro(doc.year)}</p>
      <div className="table-wrap" tabIndex={0}>
        <table>
          <thead><tr><th scope="col">{S.onelift.colWhere}</th><th scope="col">{S.onelift.colHours(doc.year)}</th>
            <th scope="col">{S.onelift.colGain}</th></tr></thead>
          <tbody>{groups.map((g) => (
            <tr key={`${g.station}-${g.ids[0]}`}>
              <th scope="row">{g.station}: {S.onelift.runs(g.kind, g.ids[0], g.ids.length - 1)}</th>
              <td>{Math.round(g.hours)}</td><td>{g.gain}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {naive && <p>{S.onelift.contrast(naive.station, naive.k_gains_baseline, Math.round(naive.hours_2025), doc.year)}</p>}
      <p className="muted">{S.onelift.method(doc.exactness_checked)}</p>
    </section>
  );
}
