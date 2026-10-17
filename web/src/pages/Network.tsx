import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { getClaims, getContingency, type Scope } from "../api";
import type { Camera } from "../components/LiveMap";
import { href } from "../router";
import { S } from "../strings.en";

type Tab = keyof typeof S.net.tabs;
const LiveMap = lazy(() => import("../components/LiveMap").then((m) => ({ default: m.LiveMap })));
const NET_CAMERA: Camera = { lng: -71.085, lat: 42.345, zoom: 10.7, pitch: 50, bearing: -8 };
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const TABS = Object.keys(S.net.tabs) as Tab[];

/** The network view: what a closure does to journeys between stations, critical pairs, travel times. */
export function Network({ scope }: { scope: Scope }) {
  const [c, setC] = useState<Record<string, any> | null>(null);
  const [claims, setClaims] = useState<Record<string, any> | null>(null);
  const [tab, setTab] = useState<Tab>("spof");
  const [arcLift, setArcLift] = useState<string | null>(null);
  useEffect(() => {
    getContingency(scope).then(setC).catch(() => {});
    getClaims().then(setClaims).catch(() => {});
  }, [scope]);
  if (!c) return <p aria-busy="true">…</p>;
  const name = (s: string) => c.names[s] ?? s;
  const now = c.now?.data ?? {};
  const mc = c.monte_carlo?.q?.[String(c.q_assumed)];
  const cutOff = new Set<string>(c.network_spof.flatMap((x: any) => x.cut_off));
  const arcEntry = arcLift ? c.network_spof.find((x: any) => x.facility_id === arcLift) : null;
  const arcHighlight = arcEntry ? new Set<string>([arcEntry.station_id, ...arcEntry.dominates_for]) : cutOff;

  function onKey(e: React.KeyboardEvent, i: number) {
    const j = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
    if (j === null) return;
    const t = TABS[(j + TABS.length) % TABS.length];
    setTab(t);
    document.getElementById(`tab-${t}`)?.focus();
  }

  return (
    <>
      <p className="eyebrow">{S.net.eyebrow}</p>
      <h1>{S.net.title}</h1>
      <p className="lead">{S.net.intro}</p>
      {claims && <>
        <div className="tiles" aria-hidden="true">
          <div className="tile" data-k="1"><span className="n">{claims.net_platform_spof_lifts}</span><span className="l">{S.net.tilePlatform}</span></div>
          <div className="tile" data-k="0"><span className="n">{claims.net_spof_lifts}</span><span className="l">{S.net.tileStation}</span></div>
          <div className="tile" data-k="0"><span className="n">{claims.net_cut_off_stations}</span><span className="l">{S.net.tileCutOff}</span></div>
          <div className="tile" data-k="2"><span className="n">{claims.net_rescued_lifts}</span><span className="l">{S.net.tileRescued}</span></div>
        </div>
        <p className="count-line"><strong>{S.net.headline(claims.net_platform_spof_lifts, claims.net_spof_lifts)}</strong></p>
      </>}
      <p className="muted">{S.net.method}</p>

      <div className="split">
        <section aria-labelledby="now-h" className="card">
          <h2 id="now-h">{S.net.nowTitle}</h2>
          <p className="visually-hidden">{cap(c.now?.summary ?? "")}</p>
          <div className="tiles compact" aria-hidden="true">
            <div className="tile" data-k={now.journeys_broken ? "0" : undefined}><span className="n">{now.journeys_broken ?? 0}</span>
              <span className="l">{S.net.tileBroken}</span></div>
            <div className="tile" data-k="1"><span className="n">{(now.last_link ?? []).length}</span><span className="l">{S.net.tileLastLink}</span></div>
            <div className="tile" data-k="1"><span className="n">{(now.critical_pairs ?? []).length}</span><span className="l">{S.net.tilePairs}</span></div>
          </div>
          {(now.last_link ?? []).length > 0 && <>
            <h3>{S.net.lastLinkTitle}</h3>
            <ul className="link-list">
              {now.last_link.map((x: any) => (
                <li key={x.facility_id}>
                  <a href={href(`/station/${x.station_id}`)}>{S.net.lastLink(x.facility_id, name(x.station_id), x.journeys)}</a>
                </li>
              ))}
            </ul>
          </>}
          {(now.critical_pairs ?? []).length > 0 && <>
            <h3>{S.net.pairsNow}</h3>
            <ul className="link-list">{now.critical_pairs.map((p: any) => (
              <li key={`${p.a}-${p.b}`}>{S.net.pairNow(p.closed.join(" + "), [p.a, p.b].filter((x: string) => !p.closed.includes(x)).join(" + "),
                name(p.station_id), p.platform_directions)}</li>
            ))}</ul>
          </>}
        </section>
        <section aria-labelledby="nm-h" className="net-map">
          <h2 id="nm-h">{S.net.mapTitle}</h2>
          <p className="muted small">{S.net.mapPick}</p>
          <div className="lift-chips" role="group" aria-label={S.net.mapPick}>
            {[...c.network_spof].sort((a: any, b: any) => name(a.station_id).localeCompare(name(b.station_id))).map((x: any) => (
              <button key={x.facility_id} aria-pressed={arcLift === x.facility_id}
                      onClick={() => setArcLift(arcLift === x.facility_id ? null : x.facility_id)}>
                <span className="mono">{x.facility_id}</span> {name(x.station_id)}
              </button>
            ))}
          </div>
          <div className="net-map-frame">
            <Suspense fallback={<div className="livemap" aria-hidden="true" />}>
              <LiveMap camera={NET_CAMERA} highlight={arcHighlight} arcLifts={arcLift ? [arcLift] : []} rise={arcLift ? 0.35 : 1}
                       labels={arcLift ? [arcEntry?.station_id ?? ""] : []} interactive />
            </Suspense>
          </div>
          <p className="small" aria-live="polite">{arcEntry ? S.net.arcText(arcEntry.facility_id, name(arcEntry.station_id), arcEntry.od_cut)
            : S.net.mapHelp}</p>
        </section>
      </div>

      <div role="tablist" aria-label={S.net.title} className="tabs">
        {TABS.map((t, i) => (
          <button key={t} id={`tab-${t}`} role="tab" aria-selected={tab === t} aria-controls={`panel-${t}`}
                  tabIndex={tab === t ? 0 : -1} onClick={() => setTab(t)} onKeyDown={(e) => onKey(e, i)}>
            {S.net.tabs[t]}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} tabIndex={0}>
        {tab === "spof" && (
          <Table head={[S.net.colLift, S.net.colStation, S.net.colJourneys, S.net.colCutOff]}
                 rows={c.network_spof.map((x: any) => [x.facility_id, <a href={href(`/station/${x.station_id}`)}>{name(x.station_id)}</a>,
                   x.od_cut, x.cut_off.map(name).join(", ")])} />
        )}
        {tab === "rescued" && (
          <Table head={[S.net.colLift, S.net.colStation, S.net.colSlowed, S.net.colWorst]}
                 rows={c.rescued.map((x: any) => [x.facility_id, <a href={href(`/station/${x.station_id}`)}>{name(x.station_id)}</a>,
                   x.od_slow, (x.detour_max_s / 60).toFixed(1)])} />
        )}
        {tab === "pairs" && <>
          <p>{S.net.pairsIntro}</p>
          <Table head={[S.net.colPair, S.net.colStation, S.net.colDirs]}
                 rows={[...c.pairs].sort((a: any, b: any) => b.n - a.n).map((p: any) => [`${p.a} + ${p.b}`,
                   name(p.dirs[0]?.station_id), p.n])} />
        </>}
        {tab === "conditional" && <>
          <p>{S.net.conditionalIntro(c.conditional.filter((x: any) => !x.same_station).length)}</p>
          <Table head={[S.net.colWhenClosed, S.net.colBecomes, S.net.colStation, S.net.colJourneys, S.net.colSame]}
                 rows={c.conditional.map((x: any) => [x.closed, x.lift, name(x.station_lift), x.journeys,
                   x.same_station ? S.net.yes : S.net.no])} />
        </>}
        {tab === "matrix" && <Matrix c={c} name={name} />}
      </div>

      {mc && <section aria-labelledby="mc-h">
        <h2 id="mc-h">{S.net.mcTitle}</h2>
        <p>{S.net.mc((mc.mean * 100).toFixed(2), (c.q_assumed * 100).toFixed(0),
          (mc.ci95[0] * 100).toFixed(2), (mc.ci95[1] * 100).toFixed(2))}</p>
      </section>}
    </>
  );
}

function Table({ head, rows }: { head: string[]; rows: any[][] }) {
  return (
    <div className="table-wrap tall" tabIndex={0}>
      <table>
        <thead><tr>{head.map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => (
          <tr key={i}>{r.map((v, j) => j === 0 ? <th key={j} scope="row">{v}</th> : <td key={j}>{v}</td>)}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

/** Station x station travel times: a canvas heat map for sighted overview, and the chosen row as a table. */
function Matrix({ c, name }: { c: Record<string, any>; name: (s: string) => string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [from, setFrom] = useState<string>(c.stations[0]);
  const order = useMemo(() => [...c.stations.keys()].sort((a: number, b: number) =>
    name(c.stations[a]).localeCompare(name(c.stations[b]))), [c]);
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const n = c.stations.length, cell = 4;
    el.width = el.height = n * cell;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    const max = Math.max(...c.minutes.flat().filter((v: number | null) => v !== null && v >= 0));
    order.forEach((a: number, i: number) => order.forEach((b: number, j: number) => {
      const v = c.minutes[a][b];
      ctx.fillStyle = v === null ? "#888" : v < 0 ? "#b00020" : `hsl(${220 - 220 * (v / max)}, 70%, 45%)`;
      ctx.fillRect(j * cell, i * cell, cell, cell);
    }));
  }, [c, order]);
  const a = c.stations.indexOf(from);
  const row = order.filter((b: number) => b !== a).map((b: number) => [name(c.stations[b]), c.minutes[a][b]])
    .sort((x: any[], y: any[]) => x[1] - y[1]);
  return (
    <>
      <p>{S.net.matrixIntro}</p>
      <canvas ref={canvas} aria-hidden="true" className="matrix-canvas" style={{ imageRendering: "pixelated" }} />
      <p>
        <label>{S.net.from}{" "}
          <select value={from} onChange={(e) => setFrom(e.target.value)}>
            {order.map((i: number) => <option key={c.stations[i]} value={c.stations[i]}>{name(c.stations[i])}</option>)}
          </select>
        </label>
      </p>
      <Table head={[S.net.colTo, S.net.colMinutes]} rows={row} />
    </>
  );
}
