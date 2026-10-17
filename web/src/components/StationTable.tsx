import { useEffect, useMemo, useState } from "react";
import { getStations } from "../api";
import { href } from "../router";
import { S } from "../strings.en";

/** Every station with layout data: platforms, how many have lost step-free access or hang on one lift, and which
 *  lifts are closed. Filterable by name, worst first. */
export function StationTable() {
  const [stations, setStations] = useState<Awaited<ReturnType<typeof getStations>>>([]);
  const [filter, setFilter] = useState("");
  useEffect(() => { getStations().then(setStations).catch(() => {}); }, []);

  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return stations
      .filter((s) => !f || s.name.toLowerCase().includes(f))
      .sort((a, b) => b.lost - a.lost || b.single - a.single || a.name.localeCompare(b.name));
  }, [stations, filter]);
  const maxSingle = Math.max(1, ...stations.map((s) => s.single));

  return (
    <section className="block" aria-labelledby="st-h">
      <div className="section-head">
        <h2 id="st-h">{S.home.tableTitle}</h2>
        <label>
          <span className="visually-hidden">{S.home.filter}</span>
          <input type="search" value={filter} placeholder={S.home.filter} onChange={(e) => setFilter(e.target.value)} />
        </label>
      </div>
      <div className="table-wrap tall" tabIndex={0}>
        <table>
          <thead>
            <tr>
              <th scope="col">{S.home.colStation}</th><th scope="col" className="num">{S.home.colPlatforms}</th>
              <th scope="col">{S.home.colLost}</th><th scope="col">{S.home.colSingle}</th>
              <th scope="col">{S.home.colClosed}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((s) => (
              <tr key={s.id}>
                <th scope="row"><a href={href(`/station/${s.id}`)}>{s.name}</a></th>
                <td className="num">{s.platforms}</td>
                <td>{s.lost ? <span className="state" data-k="0">✕ {s.lost}</span> : <span className="muted">{S.home.none}</span>}</td>
                <td>
                  {s.single ? <span className="state" data-k="1">◆ {s.single}</span> : <span className="muted">{S.home.none}</span>}
                  {s.single > 0 && <div className="bar" aria-hidden="true"><span style={{ width: `${(100 * s.single) / maxSingle}%` }} /></div>}
                </td>
                <td>{s.closed.length ? s.closed.join(", ") : <span className="muted">{S.home.none}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
