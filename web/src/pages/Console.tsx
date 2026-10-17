import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { getClaims, getMap, getOps, getStateFor, getStations, type Scope } from "../api";
import { I } from "../components/icons";
import type { Camera } from "../components/LiveMap";
import { href } from "../router";
import { S } from "../strings.en";

const LiveMap = lazy(() => import("../components/LiveMap").then((m) => ({ default: m.LiveMap })));
const OVERVIEW: Camera = { lng: -71.075, lat: 42.345, zoom: 10.9, pitch: 48, bearing: -12 };

type Closure = { alert_id: string; facility_ids: string[]; stations: string[]; scope: string; effect: string; header: string };
type Ev = { agent: string; type: string; facility_id: string | null; playbook: string | null; kind: string | null; tool: string | null; ok: boolean | null };

/** Replays the agents' recorded tick line by line (about 3 s in all; instantly under reduced motion). */
function useReveal(n: number, ms = 3000) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (!n) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setShown(n); return; }
    setShown(0);
    let i = 0;
    const id = window.setInterval(() => { i += 1; setShown(i); if (i >= n) clearInterval(id); }, Math.max(12, ms / n));
    return () => clearInterval(id);
  }, [n, ms]);
  return shown;
}

/** Mission control: the live map in the centre, today's lift alerts on the left, the selected station or the repair
 *  queue on the right, the agents' log along the bottom. Every panel is text; the map is the only drawing. */
export function Console({ scope }: { scope: Scope }) {
  const [claims, setClaims] = useState<Record<string, any> | null>(null);
  const [state, setState] = useState<Awaited<ReturnType<typeof getStateFor>> | null>(null);
  const [stations, setStations] = useState<Awaited<ReturnType<typeof getStations>>>([]);
  const [geo, setGeo] = useState<Record<string, { lat: number; lon: number; name: string }>>({});
  const [ops, setOps] = useState<{ events: Ev[]; assessments: any[] } | null>(null);
  const [sel, setSel] = useState<string | null>(null);

  useEffect(() => {
    getClaims().then(setClaims).catch(() => {});
    getStateFor(scope).then(setState).catch(() => {});
    getStations().then(setStations).catch(() => {});
    getMap().then((m) => setGeo(Object.fromEntries(m.stations.map((s: any) => [s.id, s])))).catch(() => {});
    getOps().then((o) => setOps(o as any)).catch(() => {});
  }, [scope]);

  const closures: Closure[] = state?.closures.data.closures ?? [];
  const modelled = closures.filter((c) => c.scope === "modelled");
  const ranked: any[] = state?.priority.data.ranked ?? [];
  const newly: any[] = state?.closures.data.newly_last_lift ?? [];
  const lost: any[] = state?.closures.data.platforms_lost ?? [];
  const byId = useMemo(() => new Map(stations.map((s) => [s.id, s])), [stations]);
  const verdict = useMemo(() => new Map((ops?.assessments ?? []).map((a: any) => [a.facility_id, a])), [ops]);
  const shown = useReveal(ops?.events.length ?? 0);

  const at = sel ? geo[sel] : undefined;
  const camera = useMemo<Camera>(() => at ? { lng: at.lon, lat: at.lat, zoom: 13.4, pitch: 58, bearing: -24 } : OVERVIEW, [at]);
  const highlight = useMemo(() => (sel ? new Set([sel]) : null), [sel]);
  const st = sel ? byId.get(sel) : undefined;
  const stClosures = closures.filter((c) => sel && c.stations.includes(sel));
  const stNewly = newly.filter((n) => n.station_id === sel);
  const stLost = lost.filter((p) => p.station_id === sel);
  const stQueue = ranked.filter((r) => r.station_id === sel).slice(0, 4);

  const line = (e: Ev) => {
    const what = e.type === "incident" ? S.console.ev.incident(e.facility_id ?? "")
      : e.type === "assessment" ? S.console.ev.assessment(e.facility_id ?? "", e.playbook ?? "")
      : e.type === "tool_result" ? S.console.ev.tool(e.tool ?? "", !!e.ok)
      : e.type === "guard" ? S.console.ev.guard(!!e.ok)
      : e.type === "proposal" ? S.console.ev.proposal(e.kind ?? "", e.facility_id ?? "")
      : e.type === "rider_notice" ? S.console.ev.notice(e.facility_id ?? "")
      : S.console.ev.other(e.type);
    return what;
  };

  return (
    <div className="console">
      <h1 className="visually-hidden">{S.console.title}</h1>
      <section className="kpis" aria-label={S.console.kpiLabel}>
        {claims && <>
          <div className="kpi" data-k="1"><span className="kpi-l">{S.console.kpiSingle}</span>
            <span className="kpi-n">{claims.platforms_single_lift}<small>/{claims.platforms_step_free}</small></span></div>
          <div className="kpi" data-k="1"><span className="kpi-l">{S.console.kpiSpof}</span><span className="kpi-n">{claims.spof_lifts}</span></div>
          <div className="kpi" data-k="0"><span className="kpi-l">{S.console.kpiNet}</span><span className="kpi-n">{claims.net_spof_lifts}</span></div>
          <div className="kpi" data-k={lost.length ? "0" : undefined}><span className="kpi-l">{S.console.kpiLost}</span><span className="kpi-n">{lost.length}</span></div>
          <div className="kpi" data-k="1"><span className="kpi-l">{S.console.kpiLast}</span><span className="kpi-n">{newly.length}</span></div>
          <div className="kpi" data-k="2"><span className="kpi-l">{S.console.kpiProof}</span>
            <span className="kpi-n">{claims.falkordb_certified}<small>/{claims.maxflow_calls}</small></span></div>
        </>}
      </section>

      <section className="pane pane-alerts" aria-labelledby="al-h">
        <header className="pane-h"><h2 id="al-h"><I.alert /> {S.console.alerts}</h2><span className="pane-c">{closures.length}</span></header>
        <p className="pane-sub">{S.console.alertsSub(modelled.length, closures.length - modelled.length)}</p>
        <ul className="feed">
          {closures.map((c) => {
            const sid = c.stations[0];
            const v = verdict.get(c.facility_ids[0]);
            const active = sel && sid === sel;
            return (
              <li key={c.alert_id} data-scope={c.scope} aria-current={active ? "true" : undefined}>
                <button className="feed-item" disabled={!sid || c.scope !== "modelled"} onClick={() => setSel(sid === sel ? null : sid)}>
                  <span className="feed-top">
                    <span className="mono feed-fid">{c.facility_ids.join(" + ")}</span>
                    <span className="feed-station">{(sid && (geo[sid]?.name ?? sid)) || S.console.noStation}</span>
                    {v && <span className="feed-tag" data-v={v.verdict}>{S.console.verdict[v.verdict as keyof typeof S.console.verdict] ?? v.verdict}</span>}
                  </span>
                  <span className="feed-body">{c.header}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="pane pane-map" aria-labelledby="map-h">
        <h2 id="map-h" className="visually-hidden">{S.console.map}</h2>
        <Suspense fallback={<div className="livemap" aria-hidden="true" />}>
          <LiveMap camera={camera} highlight={highlight} labels={sel ? [sel] : []} interactive scale={sel ? 0.3 : 1} />
        </Suspense>
        <div className="map-hud" aria-hidden="true">
          <span><i className="sw k1" /> {S.k.one}</span><span><i className="sw k0" /> {S.k.lost}</span>
          <span><i className="sw k2" /> {S.k.many}</span><span className="muted">{S.console.mapHint}</span>
        </div>
      </section>

      <section className="pane pane-side" aria-labelledby="sd-h">
        {st ? <>
          <header className="pane-h">
            <h2 id="sd-h"><I.station /> {st.name}</h2>
            <button className="pane-x" onClick={() => setSel(null)}>{S.console.clear}</button>
          </header>
          <div className="dossier-stats">
            <div><span className="kpi-n">{st.platforms}</span><span className="kpi-l">{S.console.platforms}</span></div>
            <div data-k={st.lost ? "0" : undefined}><span className="kpi-n">{st.lost}</span><span className="kpi-l">{S.console.loseNow}</span></div>
            <div data-k={st.single ? "1" : undefined}><span className="kpi-n">{st.single}</span><span className="kpi-l">{S.console.oneLift}</span></div>
          </div>
          {stClosures.map((c) => <p key={c.alert_id} className="dossier-line" data-k="0">{S.console.closedLine(c.facility_ids.join(", "))}</p>)}
          {stNewly.map((n) => <p key={n.facility_id} className="dossier-line" data-k="1">{S.console.lastLine(n.facility_id, new Set((n.now_sole_link_for ?? []).map((x: string) => x.split(" ")[0])).size)}</p>)}
          {stLost.map((p) => <p key={p.stop_id} className="dossier-line" data-k="0">{S.console.lostLine(p.platform_name || p.name)}</p>)}
          {stQueue.length > 0 && <>
            <h3 className="pane-h3">{S.console.queueHere}</h3>
            <ol className="queue">{stQueue.map((r) => (
              <li key={r.facility_id}><span className="mono">{r.facility_id}</span> <span>{r.tier_label}</span></li>
            ))}</ol>
          </>}
          <a className="btn amber block" href={href(`/station/${st.id}`, { dir: "exit" })}>{S.console.open3d} <I.arrow /></a>
        </> : <>
          <header className="pane-h"><h2 id="sd-h"><I.repairs /> {S.console.queue}</h2><span className="pane-c">{ranked.length}</span></header>
          <p className="pane-sub">{S.console.queueSub}</p>
          <ol className="queue big">
            {ranked.slice(0, 9).map((r, i) => (
              <li key={`${r.facility_id}-${i}`} data-tier={r.tier}>
                <button className="queue-item" onClick={() => setSel(r.station_id)}>
                  <span className="q-rank">{i + 1}</span>
                  <span className="q-main"><span className="mono">{r.facility_id}</span> {geo[r.station_id]?.name ?? r.station_id}
                    <span className="q-sub">{r.tier_label}</span></span>
                  <span className="q-n">{r.departures_day}<small>{S.console.perDay}</small></span>
                </button>
              </li>
            ))}
          </ol>
          <a className="btn block" href={href("/repairs")}>{S.console.allRepairs} <I.arrow /></a>
        </>}
      </section>

      <section className="pane pane-log" aria-labelledby="lg-h">
        <header className="pane-h"><h2 id="lg-h"><I.ops /> {S.console.log}</h2>
          <span className="pane-c">{shown}/{ops?.events.length ?? 0}</span>
          <a className="pane-link" href={href("/approvals")}>{S.console.toOps} <I.arrow /></a></header>
        <ol className="log" aria-live="off" tabIndex={0} aria-label={S.console.log}>
          {(ops?.events ?? []).slice(0, shown).reverse().map((e, i) => (
            <li key={i} data-agent={e.agent}><span className="log-agent">{S.console.agents[e.agent as keyof typeof S.console.agents] ?? e.agent}</span>
              <span className="log-what">{line(e)}</span></li>
          ))}
        </ol>
      </section>
    </div>
  );
}
