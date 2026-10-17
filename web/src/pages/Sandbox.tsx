import { useEffect, useMemo, useState } from "react";
import { getLifts, getStation, whatIfClose, type Scope, type StationBundle, type StationGraph } from "../api";
import { useAnnounce } from "../components/Announcer";
import { XRay } from "../components/XRay";
import { liftRoutes } from "../lib/maxflow";
import { href, type Route } from "../router";
import { S } from "../strings.en";

type Lift = { facility_id: string; label: string; station_id: string; station: string; status: string; last_lift: boolean };
type Change = { station: string; stationId: string; platform: string; name: string; dir: "board" | "exit"; before: number;
  after: number; last: string[] };
const MAX = 3;

/** Every platform-direction of a station whose lift-disjoint routes drop when `closed` lifts close (exact, in the browser). */
function effects(b: StationBundle, closed: Set<string>): Change[] {
  const out: Change[] = [];
  const pname = (stop: string) => {
    const p = (b.redundancy.data.platforms ?? []).find((x: any) => x.stop_id === stop);
    return p ? [p.platform_name, p.name].filter(Boolean)[0] : stop;
  };
  for (const dir of ["board", "exit"] as const) {
    const g: StationGraph = b.graph[dir];
    const streets = g.nodes.filter((n) => n.kind === "street").map((n) => n.id);
    const lifts = [...new Set(g.nodes.filter((n) => n.kind === "lift" && n.facility_id && n.status !== "closed").map((n) => n.facility_id!))];
    for (const p of g.nodes.filter((n) => n.kind === "platform")) {
      const [src, dst] = dir === "board" ? [streets, [p.id]] : [[p.id], streets];
      const before = liftRoutes(g, src, dst);
      if (before === null || before === 0) continue;
      const after = liftRoutes(g, src, dst, closed) ?? before;
      if (after >= before) continue;
      const last = after === 1 ? lifts.filter((l) => !closed.has(l) &&
        liftRoutes(g, src, dst, new Set([...closed, l])) === 0) : [];
      out.push({ station: b.redundancy.data.name, stationId: g.station.id, platform: p.id, name: pname(p.id), dir, before, after, last });
    }
  }
  return out;
}

/** UI8 what-if sandbox: close up to three lifts anywhere, see exactly which platforms lose routes or access and which
 *  lifts become the last one; share it by link; confirm it in FalkorDB on a throwaway copy when the server is up. */
export function Sandbox({ route, live, scope }: { route: Route; live: boolean; scope: Scope }) {
  const [lifts, setLifts] = useState<Lift[]>([]);
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<string[]>(() => (route.query.get("close") ?? "").split(",").filter(Boolean).slice(0, MAX));
  const [bundles, setBundles] = useState<Record<string, StationBundle>>({});
  const [confirm, setConfirm] = useState<{ state: "idle" | "running" | "done" | "failed"; text?: string }>({ state: "idle" });
  const announce = useAnnounce();

  useEffect(() => { getLifts().then((d) => setLifts(d.lifts)).catch(() => {}); }, []);
  const byId = useMemo(() => new Map(lifts.map((l) => [l.facility_id, l])), [lifts]);
  const stations = useMemo(() => [...new Set(picked.map((f) => byId.get(f)?.station_id).filter(Boolean) as string[])], [picked, byId]);

  useEffect(() => {
    for (const s of stations) if (!bundles[s]) getStation(s).then((b) => setBundles((x) => ({ ...x, [s]: b }))).catch(() => {});
    const u = new URL(window.location.href);
    window.history.replaceState(null, "", `${u.pathname}${u.search}${href("/sandbox", picked.length ? { close: picked.join(",") } : {})}`);
    setConfirm({ state: "idle" });
  }, [stations, picked]);    // eslint-disable-line react-hooks/exhaustive-deps

  const closed = useMemo(() => new Set(picked), [picked]);
  const changes = useMemo(() => stations.flatMap((s) => (bundles[s] ? effects(bundles[s], closed) : [])), [stations, bundles, closed]);
  const lost = changes.filter((c) => c.after === 0);
  const newLast = [...new Set(changes.flatMap((c) => c.last))];
  useEffect(() => { if (picked.length) announce(S.sandbox.summary(picked.join(", "), lost.length, newLast.length)); },
    [picked.join(","), lost.length, newLast.length]);    // eslint-disable-line react-hooks/exhaustive-deps

  const options = useMemo(() => {
    const f = q.trim().toLowerCase();
    return lifts.filter((l) => l.status !== "closed" && !closed.has(l.facility_id) &&
      (!f || l.facility_id.includes(f) || l.station.toLowerCase().includes(f) || l.label.toLowerCase().includes(f))).slice(0, 12);
  }, [lifts, q, closed]);

  async function confirmInFalkor() {
    setConfirm({ state: "running" });
    const r = await whatIfClose(picked, scope).catch(() => null);
    if (!r || !r.ok) { setConfirm({ state: "failed", text: r?.summary ?? S.sandbox.needsLive }); return; }
    const theirs = new Set((r.data.newly_lost ?? []).map((x: any) => x.stop_id));
    const ours = new Set(lost.map((c) => c.platform));
    const same = theirs.size === ours.size && [...ours].every((x) => theirs.has(x));
    const text = same ? S.sandbox.agree(r.data.copy ?? "", ours.size) : S.sandbox.disagree([...theirs].join(", "), [...ours].join(", "));
    setConfirm({ state: "done", text }); announce(text);
  }

  return (
    <>
      <p className="eyebrow">{S.sandbox.eyebrow}</p>
      <h1>{S.sandbox.title}</h1>
      <p className="lead">{S.sandbox.lead}</p>

      <section className="card sandbox-pick" aria-labelledby="pk-h">
        <h2 id="pk-h">{S.sandbox.pickTitle(MAX)}</h2>
        <ul className="sandbox-chips" aria-label={S.sandbox.chosen}>
          {picked.map((f) => (
            <li key={f}><span className="mono">{f}</span> {byId.get(f)?.station}
              <button aria-label={S.sandbox.remove(f)} onClick={() => setPicked(picked.filter((x) => x !== f))}>×</button></li>
          ))}
          {!picked.length && <li className="muted">{S.sandbox.none}</li>}
        </ul>
        <label htmlFor="lift-q">{S.sandbox.search}</label>
        <input id="lift-q" type="search" value={q} onChange={(e) => setQ(e.target.value)} disabled={picked.length >= MAX}
               placeholder={S.sandbox.placeholder} />
        {q && picked.length < MAX && <ul className="sandbox-options">
          {options.map((l) => (
            <li key={l.facility_id}><button onClick={() => { setPicked([...picked, l.facility_id]); setQ(""); }}>
              <span className="mono">{l.facility_id}</span> <strong>{l.station}</strong> <span className="muted">{l.label}</span>
              {l.last_lift && <span className="pill" data-k="1">{S.sandbox.lastNow}</span>}
            </button></li>
          ))}
          {!options.length && <li className="muted">{S.sandbox.noMatch}</li>}
        </ul>}
      </section>

      {picked.length > 0 && <>
        <div className="tiles">
          <div className="tile" data-k={lost.length ? "0" : undefined}><span className="n">{lost.length}</span><span className="l">{S.sandbox.tileLost}</span></div>
          <div className="tile" data-k="1"><span className="n">{changes.filter((c) => c.after === 1).length}</span><span className="l">{S.sandbox.tileOne}</span></div>
          <div className="tile" data-k={newLast.length ? "1" : undefined}><span className="n">{newLast.length}</span><span className="l">{S.sandbox.tileLast}</span></div>
          <div className="tile"><span className="n">{changes.length}</span><span className="l">{S.sandbox.tileFewer}</span></div>
        </div>
        <p role="status" className="sim-banner">{S.sandbox.banner} {S.sandbox.summary(picked.join(", "), lost.length, newLast.length)}</p>
        <p>
          <button className="primary" disabled={!live || confirm.state === "running"} onClick={() => void confirmInFalkor()}>
            {S.sandbox.confirm}</button>{" "}
          <button onClick={() => navigator.clipboard?.writeText(window.location.href).then(() => announce(S.sandbox.copied)).catch(() => {})}>
            {S.sandbox.share}</button>{" "}
          {!live && <span className="muted small">{S.sandbox.needsLive}</span>}
          {confirm.text && <span className={`chip ${confirm.state === "done" ? "ok" : ""}`}>{confirm.text}</span>}
        </p>

        <section className="block" aria-labelledby="df-h">
          <h2 id="df-h">{S.sandbox.diffTitle}</h2>
          {changes.length === 0 ? <p>{S.sandbox.noEffect}</p> : (
            <div className="table-wrap" tabIndex={0}>
              <table>
                <thead><tr><th scope="col">{S.sandbox.colPlatform}</th><th scope="col">{S.sandbox.colStation}</th>
                  <th scope="col" className="num">{S.sandbox.colBefore}</th><th scope="col" className="num">{S.sandbox.colAfter}</th>
                  <th scope="col">{S.sandbox.colLast}</th></tr></thead>
                <tbody>{changes.sort((a, b) => a.after - b.after).map((c) => (
                  <tr key={`${c.platform}-${c.dir}`}>
                    <th scope="row">{c.name} <span className="muted">{S.matrix.dir[c.dir]}</span></th>
                    <td><a href={href(`/station/${c.stationId}`, { dir: c.dir })}>{c.station}</a></td>
                    <td className="num">{c.before}</td>
                    <td className="num"><span className="state" data-k={c.after === 0 ? "0" : c.after === 1 ? "1" : "2"}>
                      {c.after === 0 ? "✕" : c.after === 1 ? "◆" : "●"} {c.after}</span></td>
                    <td>{c.last.length ? c.last.join(", ") : <span className="muted">–</span>}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </section>

        <section className="block" aria-labelledby="bx-h">
          <h2 id="bx-h">{S.sandbox.xrayTitle}</h2>
          {stations.map((s) => bundles[s] && (
            <div key={s} className="before-after">
              <h3>{bundles[s].redundancy.data.name}</h3>
              <div className="grid2">
                <figure><figcaption className="muted small">{S.sandbox.before}</figcaption>
                  <XRay graph={bundles[s].graph.exit} routeEdges={new Map()} lastLifts={new Set()} pulse={new Set()} simClosed={new Set()} /></figure>
                <figure><figcaption className="muted small">{S.sandbox.after}</figcaption>
                  <XRay graph={bundles[s].graph.exit} routeEdges={new Map()} lastLifts={new Set(newLast)} pulse={new Set(newLast)} simClosed={closed} /></figure>
              </div>
            </div>
          ))}
        </section>
      </>}
    </>
  );
}
