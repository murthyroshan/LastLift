import { useEffect, useMemo, useState } from "react";
import { getStationFor, getWhatIf, type Scope, type StationBundle, type StationGraph, type WhatIfBundle } from "../api";
import { useAnnounce } from "../components/Announcer";
import { KState } from "../components/KState";
import { XRay } from "../components/XRay";
import { href, type Route } from "../router";
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

  async function simulate(fid: string) {
    setSimError("");
    const data = await getWhatIf(id, fid, live, scope).catch(() => null);
    if (!data || !data.graph[dir]) { setSimError(data ? data.whatif.summary : S.whatif.needsLive); return; }
    setSim({ fid, data });
    announce(S.whatif.announce(data.whatif.summary));
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

  return (
    <>
      <p><a href={href("/")}>{S.station.back}</a></p>
      <h1>{red.data.name}</h1>
      <p>{S.station.summary(platforms.length,
        platforms.filter((p) => p.board?.k === 0 || p.exit?.k === 0).length,
        platforms.filter((p) => (p.board?.k === 1 || p.exit?.k === 1) && p.board?.k !== 0 && p.exit?.k !== 0).length,
        (red.data.closed_here ?? []).join(", "))}</p>
      {newlyOnly.length > 0 && <ul>{newlyOnly.map((t) => <li key={t}>{t}</li>)}</ul>}
      <div role="group" aria-label={S.station.xrayTitle} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        {(["board", "exit"] as Dir[]).map((d) => (
          <a key={d} className={`btn ${d === dir ? "primary" : ""}`} aria-current={d === dir ? "true" : undefined}
             href={href(`/station/${id}`, { dir: d })}
             style={{ display: "inline-flex", alignItems: "center", textDecoration: "none" }}>
            {d === "board" ? S.station.dirBoard : S.station.dirExit}
          </a>
        ))}
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

      <h2>{S.station.xrayTitle}</h2>
      <XRay graph={shown} routeEdges={routeEdges} lastLifts={lastLifts} pulse={pulse} simClosed={simClosed} />
      <p className="muted">{S.station.xrayCaption} {S.station.receipt(shown.receipt.flow_ms)}</p>

      <div className="grid2">
        <section aria-labelledby="pl-h">
          <h2 id="pl-h">{S.station.platformsTitle}</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th scope="col">{S.station.colPlatform}</th><th scope="col">{S.station.colBoard}</th>
                <th scope="col">{S.station.colExit}</th></tr></thead>
              <tbody>
                {platforms.map((p) => (
                  <tr key={p.stop_id} aria-selected={selected === p.stop_id}>
                    <th scope="row">
                      <button className="link" aria-pressed={selected === p.stop_id}
                              onClick={() => setSelected(selected === p.stop_id ? null : p.stop_id)}>
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
          <ul>
            {lifts.map((n) => {
              const st = sim?.fid === n.facility_id ? S.station.statusSim : n.status === "closed" ? S.station.statusClosed
                : n.status === "unknown" ? S.station.statusUnknown : S.station.statusOpen;
              return (
                <li key={n.id}>
                  <strong>{n.facility_id}</strong> {n.label}: {st}
                  {n.last_lift?.length ? <> · <span className="lastlift-badge">{S.station.lastLiftFor(n.last_lift.join(", "))}</span></> : null}
                  {n.status === "open" && !sim && (
                    <> <button onClick={() => simulate(n.facility_id!)}>{S.station.simulate(n.facility_id!)}</button></>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      </div>

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
