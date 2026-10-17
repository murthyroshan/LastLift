import { useEffect, useMemo, useState } from "react";
import { getStationFor, type StationBundle } from "../../api";
import { Station3D } from "../../components/three/Station3D";
import type { Route } from "../../router";

/** #/lab/station3d?id=place-alfcl&dir=exit : the 3D station on its own, with a platform picker. */
export function Station3DLab({ route }: { route: Route }) {
  const id = route.query.get("id") ?? "place-alfcl";
  const dir = route.query.get("dir") === "board" ? "board" : "exit";
  const [b, setB] = useState<StationBundle | null>(null);
  const [selected, setSelected] = useState<string | null>(route.query.get("pick"));
  // ?sim=813 closes a lift in the drawing only; ?pulse=891 plays the last-lift shockwave
  const simClosed = useMemo(() => new Set((route.query.get("sim") ?? "").split(",").filter(Boolean)), [route]);
  const pulse = useMemo(() => new Set((route.query.get("pulse") ?? "").split(",").filter(Boolean)), [route]);
  const [flowKey, setFlowKey] = useState(0);
  useEffect(() => { getStationFor(id, "demo").then(setB).catch(() => {}); }, [id]);
  const g = b?.graph[dir];
  const routeEdges = useMemo(() => {
    const m = new Map<string, string>();
    for (const r of g?.routes ?? []) if (r.platform_id === selected) for (const e of r.edge_ids) if (!m.has(e)) m.set(e, r.label);
    return m;
  }, [g, selected]);
  const lastLifts = useMemo(() => new Set((g?.nodes ?? []).filter((n) => n.last_lift?.length && n.facility_id).map((n) => n.facility_id!)), [g]);
  if (!g || !b) return <p aria-busy="true">…</p>;
  return (
    <div style={{ display: "grid", gap: "0.5rem" }}>
      <h1 style={{ margin: 0 }}>{b.redundancy.data.name}</h1>
      <p style={{ display: "flex", flexWrap: "wrap", gap: 4, margin: 0 }}>
        {g.platforms.map((p) => (
          <button key={p.id} aria-pressed={selected === p.id} onClick={() => setSelected(p.id === selected ? null : p.id)}>{p.name}</button>
        ))}
        <button onClick={() => setFlowKey((k) => k + 1)}>Replay flow</button>
      </p>
      <div style={{ height: "72vh" }}>
        <Station3D graph={g} stationName={b.redundancy.data.name} selected={selected} onPick={(p) => setSelected(p === selected ? null : p)}
                   routeEdges={routeEdges} lastLifts={lastLifts} pulse={pulse} simClosed={simClosed} flowKey={flowKey} />
      </div>
    </div>
  );
}
