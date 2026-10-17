import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { getStationFor, getWhatIf, type Scope, type StationBundle, type StationGraph, type WhatIfBundle } from "../api";
import { useAnnounce } from "../components/Announcer";
import { KState } from "../components/KState";
import { HistoryPanel } from "../components/HistoryPanel";
import { ProofPanel } from "../components/ProofPanel";
import { XRay } from "../components/XRay";

const Station3D = lazy(() => import("../components/three/Station3D").then((m) => ({ default: m.Station3D })));
const webgl = () => { try { return !!document.createElement("canvas").getContext("webgl2"); } catch { return false; } };
import { href, type Route } from "../router";
import { chord, play, setSoundOn, soundOn, type Plan } from "../sonify";
import { S } from "../strings.en";

type Dir = "board" | "exit";

export function Station({ route, live, scope }: { route: Route; live: boolean; scope: Scope }) {
  const id = route.parts[1];
  const dir: Dir = route.query.get("dir") === "exit" ? "exit" : "board";
  const [bundle, setBundle] = useState<StationBundle | null>(null);
  const [missing, setMissing] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [sim, setSim] = useState<{ fid: string; data: WhatIfBundle } | null>(null);
  const [simError, setSimError] = useState("");
  const [flowKey, setFlowKey] = useState(0);
  const [view, setView] = useState<"3d" | "plan">(() => (route.query.get("view") === "plan" || !webgl() ? "plan" : "3d"));
  const [sound, setSound] = useState(soundOn());
  const [volume, setVolume] = useState(0.6);
  const announce = useAnnounce();

  useEffect(() => {
    setBundle(null); setMissing(false); setSim(null); setSelected(null);
    getStationFor(id, scope).then(setBundle).catch(() => setMissing(true));
  }, [id, scope]);

  const base: StationGraph | undefined = bundle?.graph[dir];
  const shown: StationGraph | undefined = (sim?.data.graph[dir] as StationGraph | undefined) ?? base;
  const red = bundle?.redundancy;

  // Platforms whose redundancy changed under the simulation (the "2 → 1" counter).
  const changes = useMemo(() => {
    if (!sim || !base || !shown) return [];
    const key = dir === "board" ? "k_board" : "k_exit";
    return shown.platforms.flatMap((p) => {
      const before = base.platforms.find((q) => q.id === p.id)?.[key];
      const after = p[key];
      return typeof before === "number" && typeof after === "number" && after < before
        ? [{ name: p.name, before, after }] : [];
    });
  }, [sim, base, shown, dir]);

  const lastLifts = useMemo(() => new Set((shown?.nodes ?? []).filter((n) => n.last_lift?.length && n.facility_id)
    .map((n) => n.facility_id!)), [shown]);
  const pulse = useMemo(() => {
    if (!sim || !base) return new Set<string>();
    const before = new Set(base.nodes.filter((n) => n.last_lift?.length).map((n) => n.facility_id));
    return new Set([...lastLifts].filter((f) => !before.has(f)));
  }, [sim, base, lastLifts]);
  const simClosed = useMemo(() => new Set(sim ? [sim.fid] : []), [sim]);

  const routeEdges = useMemo(() => {
    const m = new Map<string, string>();
    for (const r of shown?.routes ?? []) {
      if (!selected || r.platform_id === selected) for (const e of r.edge_ids) if (!m.has(e)) m.set(e, r.label);
    }
    return selected ? m : new Map<string, string>();
  }, [shown, selected]);

  function routesFor(g: StationGraph | undefined, stop: string | null) {
    return (g?.routes ?? []).filter((r) => r.platform_id === stop).map((r) => ({ label: r.label, lifts: r.lifts }));
  }

  function describe(p: Plan, dropped?: string): string {
    const base = p.earcon ? S.sound.none : p.tremolo ? S.sound.one : S.sound.many(p.active);
    return dropped ? `${S.sound.dropped(dropped)} ${base}` : base;
  }

  async function hear(fid?: string) {
    if (!sound || !selected) return;
    const routes = routesFor(base, selected);
    const plan = routes.length ? chord(routes, fid ? [fid] : []) : { voices: [], active: 0, tremolo: false, earcon: true };
    const before = fid ? chord(routes) : undefined;
    announce(describe(plan, fid));
    await play(plan, volume, before).catch(() => {});
  }

  async function simulate(fid: string) {
    setSimError("");
    const data = await getWhatIf(id, fid, live, scope).catch(() => null);
    if (!data || !data.graph[dir]) { setSimError(data ? data.whatif.summary : S.whatif.needsLive); return; }
    setSim({ fid, data });
    announce(S.whatif.announce(data.whatif.summary));
    if (sound && selected) void hear(fid);
  }

  if (missing) return <><p><a href={href("/")}>{S.station.back}</a></p><p>{S.station.cannotAssess}</p></>;
  if (!bundle || !base || !shown || !red) return <p aria-busy="true">…</p>;
  const platforms: any[] = red.data.platforms ?? [];
  // "lift 813 is newly the only lift, because 961 is closed": a single-lift dependency that current closures created
  const newlyOnly = [...new Set(platforms.flatMap((p) => (["board", "exit"] as Dir[]).flatMap((d) => {
    const x = p[d];
    return x && x.k === 1 && typeof x.k_before_closures === "number" && x.k_before_closures >= 2 && red.data.closed_here?.length
      ? [S.station.newlyOnly((x.last_lift ?? []).join("/"), red.data.closed_here.join(", "))] : [];
  })))];
  const lifts = shown.nodes.filter((n) => n.kind === "lift");
  const platformName = (stop: string) => {
    const p = platforms.find((x) => x.stop_id === stop);
    return p ? [p.platform_name, p.name].filter(Boolean)[0] : stop;
  };

  const nLost = platforms.filter((p) => p.board?.k === 0 || p.exit?.k === 0).length;
  const nSingle = platforms.filter((p) => (p.board?.k === 1 || p.exit?.k === 1) && p.board?.k !== 0 && p.exit?.k !== 0).length;
  const pick = (stop: string) => setSelected(selected === stop ? null : stop);

  return (
    <>
      <p className="crumbs"><a href={href("/")}><span aria-hidden="true">← </span>{S.station.back}</a></p>
      <div className="station-hero">
        <div>
          <p className="eyebrow">{S.station.eyebrow}</p>
          <h1>{red.data.name}</h1>
          <p className="muted">{S.station.summary(platforms.length, nLost, nSingle, (red.data.closed_here ?? []).join(", "))}</p>
          {newlyOnly.length > 0 && <ul className="newly">{newlyOnly.map((t) => <li key={t}>{t}</li>)}</ul>}
        </div>
        <div className="tiles" aria-hidden="true">
          <div className="tile"><span className="n">{platforms.length}</span><span className="l">{S.station.tilePlatforms}</span></div>
          <div className="tile" data-k={nLost ? "0" : undefined}><span className="n">{nLost}</span><span className="l">{S.station.tileLost}</span></div>
          <div className="tile" data-k={nSingle ? "1" : undefined}><span className="n">{nSingle}</span><span className="l">{S.station.tileSingle}</span></div>
          <div className="tile"><span className="n">{lifts.length}</span><span className="l">{S.station.tileLifts}</span></div>
        </div>
      </div>

      {sim && (
        <div className="sim-banner" role="region" aria-label={S.whatif.banner}>
          <span>{S.whatif.banner}</span>
          <span>{sim.data.whatif.summary}</span>
          {changes.map((c) => (
            <span key={c.name} className="odometer">{c.name}: <s>{c.before}</s> → {c.after} {S.k.many}</span>
          ))}
          {pulse.size > 0 && [...pulse].map((f) => <span key={f} className="lastlift-badge">{S.whatif.lastLift} {f}</span>)}
          <button onClick={() => { setSim(null); announce(S.whatif.reset); }}>{S.whatif.reset}</button>
        </div>
      )}
      {simError && <p role="alert">{simError}</p>}

      <div className="station-layout">
        <section className="card xray-card" aria-labelledby="xr-h">
          <div className="xray-head">
            <h2 id="xr-h">{S.station.xrayTitle}</h2>
            <div role="group" aria-label={S.station.dirLabel} className="seg">
              {(["board", "exit"] as Dir[]).map((d) => (
                <a key={d} aria-current={d === dir ? "true" : undefined} href={href(`/station/${id}`, { dir: d })}>
                  {d === "board" ? S.station.dirBoard : S.station.dirExit}
                </a>
              ))}
            </div>
          </div>
          <div className="xray-sub">
            {!selected ? <p className="muted xray-hint-line">{S.station.pickHint}</p> : <span />}
            <div role="group" aria-label={S.station.viewLabel} className="seg small">
              <button aria-pressed={view === "3d"} onClick={() => setView("3d")}>{S.station.view3d}</button>
              <button aria-pressed={view === "plan"} onClick={() => setView("plan")}>{S.station.viewPlan}</button>
            </div>
          </div>
          {view === "3d" ? (
            <div className="s3d-frame">
              <Suspense fallback={<div className="s3d-loading" aria-hidden="true" />}>
                <Station3D graph={shown} stationName={red.data.name} selected={selected} onPick={pick} routeEdges={routeEdges}
                           lastLifts={lastLifts} pulse={pulse} simClosed={simClosed} flowKey={flowKey} />
              </Suspense>
            </div>
          ) : (
            <XRay graph={shown} routeEdges={routeEdges} lastLifts={lastLifts} pulse={pulse} simClosed={simClosed}
                  selected={selected} onPick={pick}
                  flow={selected ? shown.routes.filter((r) => r.platform_id === selected)
                    .map((r) => ({ label: r.label, edgeIds: r.edge_ids })) : []} flowKey={flowKey} />
          )}
          <ul className="xray-legend" aria-hidden="true">
            <li><span className="sw route-a" /><span className="sw route-b" /><span className="sw route-c" />{S.station.legendRoute}</li>
            <li><span className="sw closed" />{S.station.legendClosed}</li>
            <li><span className="sw sim" />{S.station.legendSim}</li>
            <li><span className="sw last" />{S.station.legendLast}</li>
          </ul>
          <p className="muted xray-caption">
            {S.station.xrayCaption} {S.station.receipt(shown.receipt.flow_ms)}
            {selected && <> <button className="link" onClick={() => setFlowKey((k) => k + 1)}>{S.station.showFlow}</button></>}
          </p>
          <div className="sound-controls" role="group" aria-label={S.sound.label}>
            <button aria-pressed={sound} onClick={() => { setSound(!sound); setSoundOn(!sound); }}>{S.sound.toggle}</button>
            <label>{S.sound.volume}{" "}
              <input type="range" min={0} max={1} step={0.05} value={volume} disabled={!sound}
                     onChange={(e) => setVolume(Number(e.target.value))} />
            </label>
            <button disabled={!sound || !selected} onClick={() => void hear()}>{S.sound.play}</button>
            <span className="muted">{selected ? S.sound.legend : S.sound.pick}</span>
          </div>
        </section>

        <div className="side-stack">
          <section aria-labelledby="pl-h">
            <h2 id="pl-h">{S.station.platformsTitle}</h2>
            <div className="table-wrap" tabIndex={0}>
              <table className="platform-table">
                <thead><tr><th scope="col">{S.station.colPlatform}</th><th scope="col">{S.station.colBoard}</th>
                  <th scope="col">{S.station.colExit}</th></tr></thead>
                <tbody>
                  {platforms.map((p) => (
                    <tr key={p.stop_id} aria-selected={selected === p.stop_id}>
                      <th scope="row">
                        <button className="link" aria-pressed={selected === p.stop_id} onClick={() => pick(p.stop_id)}>
                          {[p.platform_name, p.name].filter(Boolean)[0]}
                        </button>
                      </th>
                      {p.board ? <td><KState k={p.board.k} /></td> : <td colSpan={2}>{p.verdict}</td>}
                      {p.exit && <td><KState k={p.exit.k} /></td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section aria-labelledby="li-h">
            <h2 id="li-h">{S.station.liftsTitle}</h2>
            <ul className="lift-list">
              {lifts.map((n) => {
                const isSim = sim?.fid === n.facility_id;
                const st = isSim ? S.station.statusSim : n.status === "closed" ? S.station.statusClosed
                  : n.status === "unknown" ? S.station.statusUnknown : S.station.statusOpen;
                const k = isSim ? "sim" : n.status === "closed" ? "0" : n.status === "unknown" ? "none" : "2";
                return (
                  <li key={n.id} className="lift-card" data-status={isSim ? "sim" : n.status}
                      data-last={n.last_lift?.length ? "true" : undefined}>
                    <span className="fid">{n.facility_id}</span>
                    <span className="row">
                      <span className="pill" data-k={k}>{st}</span>
                      {n.last_lift?.length ? <span className="lastlift-badge">{S.station.lastLiftFor(n.last_lift.join(", "))}</span> : null}
                    </span>
                    <span className="lbl">{n.label}</span>
                    {n.status === "open" && !sim && (
                      <button onClick={() => simulate(n.facility_id!)}>{S.station.simulate(n.facility_id!)}</button>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        </div>
      </div>

      <ProofPanel stationId={id} stop={selected} dir={dir} name={selected ? platformName(selected) : ""} live={live}
                  scope={scope} routes={(base.routes ?? []).filter((r) => r.platform_id === selected)}
                  kNow={(platforms.find((p) => p.stop_id === selected)?.[dir]?.k as number | undefined) ?? null}
                  closedHere={red.data.closed_here ?? []} />

      <HistoryPanel stationId={id} platformName={platformName} />

      <section aria-labelledby="ro-h">
        <h2 id="ro-h">{S.station.routesTitle}</h2>
        {shown.routes.filter((r) => !selected || r.platform_id === selected).length === 0 && <p>{S.station.noRoute}</p>}
        <ul>
          {shown.routes.filter((r) => !selected || r.platform_id === selected).map((r) => (
            <li key={`${r.platform_id}-${r.label}`}>
              {S.station.routeFor(r.label, platformName(r.platform_id))}: {r.text.join(", ")}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
