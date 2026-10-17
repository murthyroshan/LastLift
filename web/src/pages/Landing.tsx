import { useEffect, useMemo, useState } from "react";
import { getClaims, getStateFor, getStations, type Scope } from "../api";
import { ClayModel } from "../components/ClayModel";
import { TheCount } from "../components/TheCount";
import { realGpu } from "../lib/gpu";
import { href } from "../router";
import { S } from "../strings.en";

const BASE = import.meta.env.BASE_URL;

export function Landing({ scope }: { scope: Scope }) {
  const [state, setState] = useState<Awaited<ReturnType<typeof getStateFor>> | null>(null);
  const [stations, setStations] = useState<Awaited<ReturnType<typeof getStations>>>([]);
  const [claims, setClaims] = useState<Record<string, any> | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    getStateFor(scope).then(setState).catch(() => {});
    getStations().then(setStations).catch(() => {});
    getClaims().then(setClaims).catch(() => {});
  }, [scope]);

  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return stations
      .filter((s) => !f || s.name.toLowerCase().includes(f))
      .sort((a, b) => b.lost - a.lost || b.single - a.single || a.name.localeCompare(b.name));
  }, [stations, filter]);
  const maxSingle = Math.max(1, ...stations.map((s) => s.single));

  const c = state?.closures.data;
  return (
    <>
      <section className="hero-light" aria-labelledby="hero-h">
        <div className="hero-copy">
          <p className="eyebrow">{S.home.eyebrow}</p>
          <h1 id="hero-h">{S.tagline}</h1>
          {claims && <>
            <p className="count ci-count">{S.home.countLead(claims.platforms_single_lift, claims.platforms_step_free)}</p>
            <p className="hero-line">{S.home.countText}</p>
          </>}
          <div className="hero-ctas">
            <a className="btn primary" href={`${BASE}concepts/sequence.html`}>{S.hero.story} <span aria-hidden="true">→</span></a>
            <a className="btn" href={`${BASE}concepts/world.html`}>{S.hero.walk}</a>
            <a className="btn" href={href("/console")}>{S.hero.console}</a>
          </div>
        </div>
        <div className="hero-model">
          {realGpu() ? <ClayModel stationId="place-alfcl" dir="exit" selected="70061" height="100%" />
            : <img src={`${BASE}concepts/sequence/frames/f119.webp`} alt="" />}
        </div>
      </section>
      <div className="after-intro">
      {c && (
        <section className="block" aria-labelledby="now-h">
          <div className="section-head">
            <div>
              <h2 id="now-h">{S.home.nowTitle}</h2>
              <p className="muted">{S.home.nowLead}</p>
            </div>
          </div>
          <div className="tiles">
            <div className="tile" data-k="0"><span className="n">{c.platforms_lost.length}</span>
              <span className="l">{S.home.tileLost}</span></div>
            <div className="tile" data-k="1"><span className="n">{c.newly_last_lift.length}</span>
              <span className="l">{S.home.tileLast}</span></div>
            <div className="tile"><span className="n">{c.closures.length}</span>
              <span className="l">{S.home.tileAlerts(
                c.closures.filter((x: any) => x.scope === "modelled").length,
                c.closures.filter((x: any) => x.scope !== "modelled").length)}</span></div>
          </div>
        </section>
      )}

      <section className="block card" aria-labelledby="tc-h">
        <div className="section-head">
          <div>
            <h2 id="tc-h">{S.home.countTitle}</h2>
            <p className="muted">{S.home.countHelp}</p>
          </div>
        </div>
        <TheCount />
      </section>

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
      </div>
    </>
  );
}
