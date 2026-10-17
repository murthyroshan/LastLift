import { useMemo } from "react";
import type { StationGraph } from "../api";

type Props = {
  graph: StationGraph;
  routeEdges: Map<string, string>;      // edge id -> route label (A, B, C)
  lastLifts: Set<string>;               // facility ids drawn with the LAST LIFT ring
  pulse: Set<string>;                   // facility ids that pulse (just became the last lift)
  simClosed: Set<string>;               // facility ids closed only in the simulation
};

const W = 1000, ROW = 64, TOP = 30, SIDE = 20;
const ORDER = { street: 0, entrance: 1, gate: 2, area: 3, lift: 4, platform: 5 } as const;

/** The station as a drawing: one row per step from the street (the contract's rank), routes coloured,
 *  closures dashed. Decorative for assistive technology (aria-hidden): the platform, lift and route
 *  tables carry the same facts in words. */
export function XRay({ graph, routeEdges, lastLifts, pulse, simClosed }: Props) {
  const layout = useMemo(() => {
    const rows = new Map<number, typeof graph.nodes>();
    const maxRank = Math.max(0, ...graph.nodes.map((n) => n.rank ?? 0));
    for (const n of graph.nodes) {
      const r = n.rank ?? maxRank + 1;                         // nodes with no step-free link go to the bottom
      if (!rows.has(r)) rows.set(r, []);
      rows.get(r)!.push(n);
    }
    const pos = new Map<string, { x: number; y: number; w: number }>();
    const keys = [...rows.keys()].sort((a, b) => a - b);
    keys.forEach((r, row) => {
      const ns = rows.get(r)!.sort((p, q) => ORDER[p.kind] - ORDER[q.kind] || p.id.localeCompare(q.id));
      const step = (W - 2 * SIDE) / ns.length;
      ns.forEach((n, i) => pos.set(n.id, { x: SIDE + step * (i + 0.5), y: TOP + row * ROW, w: Math.min(110, step - 6) }));
    });
    return { pos, height: TOP + keys.length * ROW };
  }, [graph]);

  const statusOf = (fid?: string, status?: string) =>
    fid && simClosed.has(fid) ? "sim" : status === "closed" ? "closed" : "";

  return (
    <svg className="xray" viewBox={`0 0 ${W} ${layout.height}`} aria-hidden="true" focusable="false">
      {graph.edges.map((e) => {
        const a = layout.pos.get(e.source), c = layout.pos.get(e.target);
        if (!a || !c) return null;
        const st = e.kind === "lift" ? statusOf(e.facility_id, e.status) : "";
        return <line key={e.id} className={`edge ${e.kind} ${st}`} x1={a.x} y1={a.y} x2={c.x} y2={c.y} />;
      })}
      {graph.edges.filter((e) => routeEdges.has(e.id)).map((e) => {
        const a = layout.pos.get(e.source), c = layout.pos.get(e.target);
        if (!a || !c) return null;
        return <line key={`r-${e.id}`} className={`edge route-${routeEdges.get(e.id)}`} x1={a.x} y1={a.y} x2={c.x} y2={c.y} />;
      })}
      {graph.nodes.map((n) => {
        const p = layout.pos.get(n.id);
        if (!p) return null;
        const fid = n.facility_id;
        const cls = ["node", n.kind, statusOf(fid, n.status), fid && lastLifts.has(fid) ? "last" : ""].join(" ");
        if (n.kind === "platform") {
          const chars = Math.max(3, Math.floor(p.w / 7));
          const text = n.label.length > chars ? `${n.label.slice(0, chars - 1)}…` : n.label;
          return (
            <g key={n.id} className={cls}>
              <title>{n.label}</title>
              <rect x={p.x - p.w / 2} y={p.y - 14} width={p.w} height={28} rx={6} />
              <text x={p.x} y={p.y + 4} textAnchor="middle">{text}</text>
            </g>
          );
        }
        if (n.kind === "lift") {
          return (
            <g key={n.id} className={cls}>
              <rect x={p.x - 18} y={p.y - 12} width={36} height={24} rx={4} />
              <text x={p.x} y={p.y + 4} textAnchor="middle">{fid}</text>
              {fid && pulse.has(fid) && <circle className="pulse" cx={p.x} cy={p.y} r={14} />}
            </g>
          );
        }
        const r = n.kind === "street" ? 7 : n.kind === "entrance" ? 5 : 3;
        return (
          <g key={n.id} className={cls}>
            <circle cx={p.x} cy={p.y} r={r} />
          </g>
        );
      })}
    </svg>
  );
}
