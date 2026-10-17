import { useEffect, useMemo, useState } from "react";
import { getLifts, getMap, getStateFor, getStation, type Scope, type StationBundle } from "../api";
import { effects, type Change } from "../lib/effects";
import { href } from "../router";
import { S } from "../strings.en";

type Lift = { facility_id: string; station_id: string; station: string; status: string };
type St = { id: string; name: string; lat: number; lon: number; data: boolean };
const W = 640, H = 560, PAD = 26, N = 12;

/** The landing's product stage: a panel of real lift buttons, the network map, and a readout. Press a lift and it
 *  closes; every platform that loses step-free access (red) or is left on one lift (amber) lights up, computed
 *  exactly in the browser from the published station layouts. The readout says the same in words. */
export function LiftPanel({ scope = "demo" }: { scope?: Scope }) {
  const [lifts, setLifts] = useState<Lift[]>([]);
  const [map, setMap] = useState<{ stations: St[]; links: { a: string; b: string; rail: boolean }[] } | null>(null);
  const [closed, setClosed] = useState<string[]>([]);
  const [bundles, setBundles] = useState<Record<string, StationBundle>>({});

  useEffect(() => {
    Promise.all([getLifts(), getStateFor(scope)]).then(([l, s]) => {   // with Live on, today's ranking
      const byId = new Map((l.lifts as Lift[]).map((x) => [x.facility_id, x]));
      const seen = new Set<string>(), pick: Lift[] = [];
      for (const r of s.priority.data.ranked as any[]) {      // the lifts that matter most, open now, one per station
        const x = byId.get(r.facility_id);
        if (!x || r.closed || x.status === "closed" || seen.has(x.station_id)) continue;
        seen.add(x.station_id); pick.push(x);
        if (pick.length === N) break;
      }
      setLifts(pick);
    }).catch(() => {});
    getMap().then(setMap).catch(() => {});
  }, [scope]);

  const stationsOf = useMemo(() => [...new Set(closed.map((f) => lifts.find((l) => l.facility_id === f)?.station_id).filter(Boolean) as string[])],
    [closed, lifts]);
  useEffect(() => {
    for (const s of stationsOf) if (!bundles[s]) getStation(s).then((b) => setBundles((x) => ({ ...x, [s]: b }))).catch(() => {});
  }, [stationsOf]);    // eslint-disable-line react-hooks/exhaustive-deps

  const changes: Change[] = useMemo(() => {
    const set = new Set(closed);
    return stationsOf.flatMap((s) => (bundles[s] ? effects(bundles[s], set) : []));
  }, [stationsOf, bundles, closed]);
  const lost = changes.filter((c) => c.after === 0);
  const one = changes.filter((c) => c.after === 1);
  const newLast = [...new Set(changes.flatMap((c) => c.last))];
  const hit = new Map<string, "lost" | "one">();
  for (const c of changes) hit.set(c.stationId, c.after === 0 ? "lost" : hit.get(c.stationId) ?? "one");

  // a transit-diagram projection: distance from downtown compressed (directions kept), the frame fitted to the
  // stations with layouts, ignoring the few far outliers so the network fills the panel
  const proj = useMemo(() => {
    if (!map) return null;
    const C = { lat: 42.356, lon: -71.062 }, k = Math.cos(C.lat * Math.PI / 180), R0 = 0.04;
    const warp = (lat: number, lon: number) => {
      const dx = (lon - C.lon) * k, dy = lat - C.lat, r = Math.hypot(dx, dy);
      const f = r ? Math.pow(r / R0, 0.58) * R0 / r : 0;
      return { x: dx * f, y: dy * f };
    };
    const pts = map.stations.filter((s) => s.data).map((s) => warp(s.lat, s.lon));
    const radii = pts.map((p) => Math.hypot(p.x, p.y)).sort((a, b) => a - b);
    const cut = radii[Math.floor(radii.length * 0.97)];
    const fit = pts.filter((p) => Math.hypot(p.x, p.y) <= cut);
    const x0 = Math.min(...fit.map((p) => p.x)), x1 = Math.max(...fit.map((p) => p.x));
    const y0 = Math.min(...fit.map((p) => p.y)), y1 = Math.max(...fit.map((p) => p.y));
    const sc = Math.min((W - 2 * PAD) / (x1 - x0), (H - 2 * PAD) / (y1 - y0));
    const ox = (W - (x1 - x0) * sc) / 2, oy = (H - (y1 - y0) * sc) / 2;
    return (lat: number, lon: number) => { const q = warp(lat, lon); return { x: ox + (q.x - x0) * sc, y: H - oy - (q.y - y0) * sc }; };
  }, [map]);

  const toggle = (f: string) => setClosed((c) => (c.includes(f) ? c.filter((x) => x !== f) : [...c, f]));
  const at = new Map((map?.stations ?? []).map((s) => [s.id, s]));
  const summary = closed.length === 0 ? S.panel.idle
    : S.panel.result(closed.join(", "), lost.length, one.length, newLast.length);

  return (
    <section className="lp" aria-labelledby="lp-h">
      <h2 id="lp-h" className="lp-title">{S.panel.title}</h2>
      <div className="lp-stage">
        <div className="lp-panel" role="group" aria-label={S.panel.buttons}>
          <p className="lp-plate" aria-hidden="true">{S.panel.plate}</p>
          <div className="lp-grid">
            {lifts.map((l, i) => {
              const on = closed.includes(l.facility_id);
              return (
                <button key={l.facility_id} className={`lp-btn ${i === 0 && !closed.length ? "hint" : ""}`} aria-pressed={on}
                        onClick={() => toggle(l.facility_id)} aria-label={S.panel.btn(l.facility_id, l.station, on)}>
                  <span className="lp-led" aria-hidden="true" />
                  <span className="lp-num">{l.facility_id}</span>
                  <span className="lp-st">{l.station}</span>
                </button>
              );
            })}
          </div>
          <button className="lp-reset" onClick={() => setClosed([])} disabled={!closed.length}>{S.panel.reset}</button>
        </div>

        <div className="lp-map" aria-hidden="true">
          {map && proj && (
            <svg viewBox={`0 0 ${W} ${H}`}>
              {map.links.filter((l) => l.rail).map((l) => {
                const a = at.get(l.a), b = at.get(l.b);
                if (!a || !b || !a.data || !b.data) return null;
                const p = proj(a.lat, a.lon), q = proj(b.lat, b.lon);
                return <line key={`${l.a}-${l.b}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} className="lp-link" />;
              })}
              {map.stations.filter((s) => s.data).map((s) => {
                const p = proj(s.lat, s.lon), h = hit.get(s.id);
                return (
                  <g key={s.id} className={`lp-st-dot ${h ?? ""}`}>
                    {h && <circle cx={p.x} cy={p.y} r={16} className="lp-ripple" />}
                    <circle cx={p.x} cy={p.y} r={h ? 7 : 3.4} />
                  </g>
                );
              })}
              {[...hit.keys()].map((id) => {
                const s = at.get(id); if (!s) return null;
                const p = proj(s.lat, s.lon);
                return <text key={`t-${id}`} x={p.x + 12} y={p.y + 5} className="lp-label">{s.name}</text>;
              })}
            </svg>
          )}
        </div>

        <div className="lp-readout">
          <div className="lp-screen" aria-hidden="true">
            <div><span className="lp-digits" data-k="lost">{String(lost.length).padStart(2, "0")}</span><span>{S.panel.rLost}</span></div>
            <div><span className="lp-digits" data-k="one">{String(one.length).padStart(2, "0")}</span><span>{S.panel.rOne}</span></div>
            <div><span className="lp-digits">{String(newLast.length).padStart(2, "0")}</span><span>{S.panel.rLast}</span></div>
          </div>
          <p className="lp-words" role="status" aria-live="polite">{summary}</p>
          {changes.length > 0 && (
            <ul className="lp-list">
              {[...lost, ...one].slice(0, 5).map((c) => (
                <li key={`${c.platform}-${c.dir}`} data-k={c.after === 0 ? "lost" : "one"}>
                  <a href={href(`/station/${c.stationId}`, { dir: c.dir })}>{c.station}</a> · {c.name} {S.matrix.dir[c.dir]}
                </li>
              ))}
              {lost.length + one.length > 5 && <li className="muted">{S.panel.more(lost.length + one.length - 5)}</li>}
            </ul>
          )}
          {closed.length > 0 && <a className="lp-deeper" href={href("/sandbox", { close: closed.slice(0, 3).join(",") })}>{S.panel.deeper}</a>}
        </div>
      </div>
    </section>
  );
}
