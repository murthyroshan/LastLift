import { useEffect, useId, useState } from "react";
import { getWorstDay, stressTest } from "../api";
import { href } from "../router";
import { S } from "../strings.en";

/** The unluckiest day: for 1-10 simultaneous lift failures, the set that leaves the most platform-directions without
 *  a step-free route (exact), and a live re-check in FalkorDB. Resilience framing: these are the lifts to protect. */
export function WorstDay({ live }: { live: boolean }) {
  const [doc, setDoc] = useState<any>(null);
  const [b, setB] = useState(5);
  const [check, setCheck] = useState("");
  const id = useId();
  useEffect(() => { getWorstDay().then(setDoc).catch(() => {}); }, []);
  if (!doc) return null;
  const row = doc.rows.find((r: any) => r.B === b);
  return (
    <section aria-labelledby="wd-h">
      <h2 id="wd-h">{S.worst.title}</h2>
      <p>{S.worst.intro}</p>
      <label htmlFor={id}>{S.worst.slider}: <strong>{b}</strong></label><br />
      <input id={id} type="range" min={1} max={10} step={1} value={b}
             onChange={(e) => { setB(Number(e.target.value)); setCheck(""); }} style={{ width: "min(100%, 22rem)" }} />
      <p aria-live="polite"><strong>{S.worst.result(b, row.platform_directions, doc.assessed_platform_directions,
        row.departures)}</strong></p>
      <ul>{row.lifts.map((l: any) => (
        <li key={l.facility_id}>{S.worst.lift(l.facility_id)}{l.station &&
          <> · <a href={href(`/station/${l.station_id}`)}>{l.station}</a></>}</li>
      ))}</ul>
      {live && <p>
        <button onClick={async () => {
          setCheck(S.worst.checking);
          const r = await stressTest(b).catch(() => null);
          setCheck(r ? S.worst.checked(r.data.observed, r.data.match) : S.worst.failed);
        }}>{S.worst.recheck}</button>{" "}<span role="status">{check}</span>
      </p>}
      <div className="table-wrap" tabIndex={0}>
        <table>
          <thead><tr><th scope="col">{S.worst.colB}</th><th scope="col">{S.worst.colDirs}</th>
            <th scope="col">{S.worst.colDeps}</th></tr></thead>
          <tbody>{doc.rows.map((r: any) => (
            <tr key={r.B} aria-current={r.B === b ? "true" : undefined}>
              <th scope="row">{r.B}</th><td>{r.platform_directions}</td><td>{r.departures}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <p className="muted">{S.worst.method}</p>
    </section>
  );
}
