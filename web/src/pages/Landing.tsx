import { useEffect, useMemo, useState } from "react";
import { getClaims, getState, getStations } from "../api";
import { href } from "../router";
import { S } from "../strings.en";

export function Landing() {
  const [claims, setClaims] = useState<Record<string, any> | null>(null);
  const [state, setState] = useState<Awaited<ReturnType<typeof getState>> | null>(null);
  const [stations, setStations] = useState<Awaited<ReturnType<typeof getStations>>>([]);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    getClaims().then(setClaims).catch(() => {});
    getState().then(setState).catch(() => {});
    getStations().then(setStations).catch(() => {});
  }, []);

  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return stations
      .filter((s) => !f || s.name.toLowerCase().includes(f))
      .sort((a, b) => b.lost - a.lost || b.single - a.single || a.name.localeCompare(b.name));
  }, [stations, filter]);

  const c = state?.closures.data;
  const firstLast = c?.newly_last_lift?.[0];
  return (
    <>
      <h1>{S.tagline}</h1>
      {claims && (
        <section className="panel" aria-labelledby="count-h">
          <h2 id="count-h" className="visually-hidden">{S.home.countText}</h2>
          <p>
            <span className="count">{S.home.countLead(claims.platforms_single_lift, claims.platforms_step_free)}</span>{" "}
            {S.home.countText}
          </p>
          <p className="muted">{S.home.certified(claims.falkordb_certified, claims.maxflow_calls)}</p>
          <ul>
            <li>{S.home.spof(claims.spof_lifts)}</li>
            <li>{S.home.naive(claims.naive_two_lifts_but_k1)}</li>
          </ul>
        </section>
      )}
      {c && (
        <section aria-labelledby="now-h">
          <h2 id="now-h">{S.home.nowTitle}</h2>
          <ul>
            <li>{S.home.nowLost(c.platforms_lost.length)}</li>
            <li>{S.home.nowLast(c.newly_last_lift.length)}</li>
            <li>{S.home.nowAlerts(c.closures.length,
              c.closures.filter((x: any) => x.scope === "modelled").length,
              c.closures.filter((x: any) => x.scope !== "modelled").length)}</li>
          </ul>
          {firstLast && (
            <a className="btn primary" href={href(`/station/${firstLast.station_id}`, { dir: "exit" })}
               style={{ display: "inline-flex", alignItems: "center", textDecoration: "none" }}>
              {S.home.seeLastLift}
            </a>
          )}
        </section>
      )}
      <section aria-labelledby="st-h">
        <h2 id="st-h">{S.home.tableTitle}</h2>
        <label>
          {S.home.filter}{" "}
          <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </label>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">{S.home.colStation}</th><th scope="col">{S.home.colPlatforms}</th>
                <th scope="col">{S.home.colLost}</th><th scope="col">{S.home.colSingle}</th>
                <th scope="col">{S.home.colClosed}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((s) => (
                <tr key={s.id}>
                  <th scope="row"><a href={href(`/station/${s.id}`)}>{s.name}</a></th>
                  <td>{s.platforms}</td>
                  <td>{s.lost ? <span className="state" data-k="0">✕ {s.lost}</span> : S.home.none}</td>
                  <td>{s.single ? <span className="state" data-k="1">◐ {s.single}</span> : S.home.none}</td>
                  <td>{s.closed.length ? s.closed.join(", ") : S.home.none}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
