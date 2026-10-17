import { useEffect, useMemo, useRef, useState } from "react";
import { getClaims, getContingency, type Scope } from "../api";
import { href } from "../router";
import { S } from "../strings.en";

type Tab = keyof typeof S.net.tabs;
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const TABS = Object.keys(S.net.tabs) as Tab[];

/** The network view: what a closure does to journeys between stations, critical pairs, travel times. */
export function Network({ scope }: { scope: Scope }) {
  const [c, setC] = useState<Record<string, any> | null>(null);
  const [claims, setClaims] = useState<Record<string, any> | null>(null);
  const [tab, setTab] = useState<Tab>("spof");
  useEffect(() => {
    getContingency(scope).then(setC).catch(() => {});
    getClaims().then(setClaims).catch(() => {});
  }, [scope]);
  if (!c) return <p aria-busy="true">…</p>;
  const name = (s: string) => c.names[s] ?? s;
  const now = c.now?.data ?? {};
  const mc = c.monte_carlo?.q?.[String(c.q_assumed)];

  function onKey(e: React.KeyboardEvent, i: number) {
    const j = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
    if (j === null) return;
    const t = TABS[(j + TABS.length) % TABS.length];
    setTab(t);
    document.getElementById(`tab-${t}`)?.focus();
  }

  return (
    <>
      <h1>{S.net.title}</h1>
      <p>{S.net.intro}</p>
      {claims && <p className="count-line"><strong>{S.net.headline(claims.net_platform_spof_lifts, claims.net_spof_lifts)}</strong></p>}
      <p className="muted">{S.net.method}</p>

      <section aria-labelledby="now-h" className="panel">
        <h2 id="now-h">{S.net.nowTitle}</h2>
        <p>{cap(c.now?.summary ?? "")}</p>
        {(now.last_link ?? []).length > 0 && <>
          <h3>{S.net.lastLinkTitle}</h3>
          <ul>
            {now.last_link.map((x: any) => (
              <li key={x.facility_id}>
                <a href={href(`/station/${x.station_id}`)}>{S.net.lastLink(x.facility_id, name(x.station_id), x.journeys)}</a>
              </li>
            ))}
          </ul>
        </>}
        {(now.critical_pairs ?? []).length > 0 && <>
          <h3>{S.net.pairsNow}</h3>
          <ul>{now.critical_pairs.map((p: any) => (
            <li key={`${p.a}-${p.b}`}>{S.net.pairNow(p.closed.join(" + "), [p.a, p.b].filter((x: string) => !p.closed.includes(x)).join(" + "),
              name(p.station_id), p.platform_directions)}</li>
          ))}</ul>
        </>}
      </section>

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
    <div className="table-wrap">
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
      <canvas ref={canvas} aria-hidden="true" style={{ width: "min(100%, 356px)", imageRendering: "pixelated" }} />
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
