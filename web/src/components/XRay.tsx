import { useEffect, useMemo, useRef } from "react";
import type { GraphNode, StationGraph } from "../api";
import { S } from "../strings.en";

type Props = {
  graph: StationGraph;
  routeEdges: Map<string, string>;      // edge id -> route label (A, B, C)
  lastLifts: Set<string>;               // facility ids drawn with the LAST LIFT ring
  pulse: Set<string>;                   // facility ids that pulse (just became the last lift)
  simClosed: Set<string>;               // facility ids closed only in the simulation
  flow?: { label: string; edgeIds: string[] }[];   // ordered routes for the flow particles
  flowKey?: number;                     // change it to replay the particles
  selected?: string | null;             // selected platform id
  onPick?: (platformId: string) => void; // mouse convenience; the platform table is the keyboard path
};

const FLOW_MS = 4500, SPEED = 90 / 1000, DOTS = 4;   // 4.5 s (under WCAG 2.2.2's 5 s), 90 px/s, 4 dots a route

const W = 1000, ROW = 84, TOP = 26, LEFT = 112, RIGHT = 16;
const ORDER = { street: 0, entrance: 1, gate: 2, area: 3, lift: 4, platform: 5 } as const;
const WEIGHT = { street: 2, entrance: 1, gate: 0.55, area: 0.55, lift: 1.5, platform: 2.6 } as const;

/** A smooth link between two points: a vertical S-curve across rows, a shallow arc within a row. */
function seg(a: { x: number; y: number }, c: { x: number; y: number }) {
  if (Math.abs(a.y - c.y) < 1) {
    const mx = (a.x + c.x) / 2, lift = Math.min(28, Math.abs(c.x - a.x) * 0.25);
    return `Q${mx},${a.y - lift} ${c.x},${c.y}`;
  }
  const my = (a.y + c.y) / 2;
  return `C${a.x},${my} ${c.x},${my} ${c.x},${c.y}`;
}

/** The station as a drawing: one band per step from the street (the contract's rank), nodes ordered to reduce
 *  crossings, routes coloured, closures dashed, and everything off the selected platform's routes dimmed.
 *  Decorative for assistive technology (aria-hidden): the platform, lift and route lists carry the same facts. */
export function XRay({ graph, routeEdges, lastLifts, pulse, simClosed, flow = [], flowKey = 0, selected = null, onPick }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const layout = useMemo(() => {
    const maxRank = Math.max(0, ...graph.nodes.map((n) => n.rank ?? 0));
    const rowsMap = new Map<number, GraphNode[]>();
    for (const n of graph.nodes) {
      const r = n.rank ?? maxRank + 1;                         // nodes with no step-free link go to the bottom
      if (!rowsMap.has(r)) rowsMap.set(r, []);
      rowsMap.get(r)!.push(n);
    }
    const keys = [...rowsMap.keys()].sort((a, b) => a - b);
    const rows = keys.map((k) => rowsMap.get(k)!.sort((p, q) => ORDER[p.kind] - ORDER[q.kind] || p.id.localeCompare(q.id)));
    const nbr = new Map<string, Set<string>>();
    for (const e of graph.edges) {
      if (!nbr.has(e.source)) nbr.set(e.source, new Set());
      if (!nbr.has(e.target)) nbr.set(e.target, new Set());
      nbr.get(e.source)!.add(e.target); nbr.get(e.target)!.add(e.source);
    }
    // barycentre sweeps (down, then up) to cut crossings; deterministic
    const order = new Map<string, number>();
    const index = () => rows.forEach((row) => row.forEach((n, i) => order.set(n.id, (i + 0.5) / row.length)));
    index();
    const sweep = (range: number[]) => {
      for (const ri of range) {
        const bc = new Map(rows[ri].map((n) => {
          const ns = [...(nbr.get(n.id) ?? [])].filter((m) => order.has(m) && !rows[ri].some((x) => x.id === m));
          return [n.id, ns.length ? ns.reduce((s, m) => s + order.get(m)!, 0) / ns.length : order.get(n.id)!];
        }));
        rows[ri].sort((p, q) => bc.get(p.id)! - bc.get(q.id)! || p.id.localeCompare(q.id));
        rows[ri].forEach((n, i) => order.set(n.id, (i + 0.5) / rows[ri].length));
      }
    };
    const down = rows.map((_, i) => i).slice(1), up = rows.map((_, i) => i).reverse().slice(1);
    for (let it = 0; it < 6; it++) { sweep(down); sweep(up); }

    const pos = new Map<string, { x: number; y: number; w: number }>();
    rows.forEach((row, ri) => {
      const total = row.reduce((s, n) => s + WEIGHT[n.kind], 0);
      const unit = (W - LEFT - RIGHT) / total;
      let x = LEFT;
      for (const n of row) {
        const w = WEIGHT[n.kind] * unit;
        pos.set(n.id, { x: x + w / 2, y: TOP + ri * ROW + ROW / 2 - 10, w });
        x += w;
      }
    });
    const PRIORITY = ["street", "platform", "lift", "entrance", "gate", "area"] as const;
    const bands = rows.map((row) => S.xray.band[PRIORITY.find((k) => row.some((n) => n.kind === k)) ?? "area"]);
    return { pos, bands, height: TOP + rows.length * ROW };
  }, [graph]);

  const onRoute = useMemo(() => {
    const ns = new Set<string>();
    const byId = new Map(graph.edges.map((e) => [e.id, e]));
    for (const id of routeEdges.keys()) { const e = byId.get(id); if (e) { ns.add(e.source); ns.add(e.target); } }
    return ns;
  }, [graph, routeEdges]);

  // undirected base links (two-way pathways drawn once)
  const links = useMemo(() => {
    const seen = new Map<string, (typeof graph.edges)[number]>();
    for (const e of graph.edges) {
      const k = [e.source, e.target].sort().join("|");
      const prev = seen.get(k);
      if (!prev || (e.status === "closed" && prev.status !== "closed")) seen.set(k, e);
    }
    return [...seen.values()];
  }, [graph]);

  const paths = useMemo(() => {
    const byId = new Map(graph.edges.map((e) => [e.id, e]));
    return flow.map((r) => {
      let d = "";
      for (const id of r.edgeIds) {
        const e = byId.get(id);
        const a = e && layout.pos.get(e.source), c = e && layout.pos.get(e.target);
        if (!a || !c) continue;
        if (!d) d = `M${a.x},${a.y}`;
        d += ` ${seg(a, c)}`;
      }
      return { label: r.label, d };
    }).filter((p) => p.d.includes("C") || p.d.includes("Q"));
  }, [flow, graph, layout]);

  useEffect(() => {                                      // particles: one rAF loop, stopped after FLOW_MS
    const svg = svgRef.current;
    if (!svg || !paths.length || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const els = [...svg.querySelectorAll<SVGPathElement>("path.flow-path")];
    const dots = [...svg.querySelectorAll<SVGCircleElement>("circle.flow-dot")];
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = now - start;
      els.forEach((p, i) => {
        const len = p.getTotalLength();
        for (let j = 0; j < DOTS; j++) {
          const at = (t * SPEED + (j * len) / DOTS) % len;
          const pt = p.getPointAtLength(at);
          const dot = dots[i * DOTS + j];
          if (dot) { dot.setAttribute("cx", String(pt.x)); dot.setAttribute("cy", String(pt.y)); }
        }
      });
      if (t < FLOW_MS && !document.hidden) raf = requestAnimationFrame(tick);
      else dots.forEach((d) => d.setAttribute("opacity", "0"));
    };
    dots.forEach((d) => d.setAttribute("opacity", "1"));
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [paths, flowKey]);

  const statusOf = (fid?: string, status?: string) =>
    fid && simClosed.has(fid) ? "sim" : status === "closed" ? "closed" : "";
  const focus = routeEdges.size > 0;

  return (
    <svg ref={svgRef} className={`xray ${focus ? "focus" : ""}`} viewBox={`0 0 ${W} ${layout.height}`} aria-hidden="true" focusable="false">
      <defs>
        <marker id="chevron" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M2,1 L8,5 L2,9" className="chevron" />
        </marker>
      </defs>
      {layout.bands.map((b, i) => (
        <g key={i}>
          {i % 2 === 0 && <rect className="band" x={0} y={TOP + i * ROW - 10} width={W} height={ROW} rx={8} />}
          <text className="band-label" x={12} y={TOP + i * ROW + ROW / 2 - 6}>{b}</text>
        </g>
      ))}
      {links.map((e) => {
        const a = layout.pos.get(e.source), c = layout.pos.get(e.target);
        if (!a || !c) return null;
        const st = e.kind === "lift" ? statusOf(e.facility_id, e.status) : "";
        return <path key={e.id} className={`edge ${e.kind} ${st}`} d={`M${a.x},${a.y} ${seg(a, c)}`} />;
      })}
      {graph.edges.filter((e) => routeEdges.has(e.id)).map((e) => {
        const a = layout.pos.get(e.source), c = layout.pos.get(e.target);
        if (!a || !c) return null;
        return <path key={`r-${e.id}`} className={`edge route route-${routeEdges.get(e.id)}`} d={`M${a.x},${a.y} ${seg(a, c)}`} />;
      })}
      {paths.map((p) => (
        <path key={`f-${p.label}`} d={p.d} className={`flow-path route-${p.label}`} markerMid="url(#chevron)" />
      ))}
      {graph.nodes.map((n) => {
        const p = layout.pos.get(n.id);
        if (!p) return null;
        const fid = n.facility_id;
        const cls = ["node", n.kind, statusOf(fid, n.status), fid && lastLifts.has(fid) ? "last" : "",
          onRoute.has(n.id) ? "on-route" : "", n.kind === "platform" && onPick ? "pick" : "",
          n.id === selected ? "selected on-route" : ""].join(" ");
        if (n.kind === "platform") {
          const w = Math.min(150, p.w - 8);
          const chars = Math.max(4, Math.floor(w / 6.6));
          const name = graph.station.name;
          const label = n.label.startsWith(`${name} `) ? n.label.slice(name.length + 1) : n.label;
          const text = label.length > chars ? `${label.slice(0, chars - 1)}…` : label;
          return (
            <g key={n.id} className={cls} onClick={onPick ? () => onPick(n.id) : undefined}>
              <title>{n.label}</title>
              <rect x={p.x - w / 2} y={p.y - 16} width={w} height={32} rx={8} />
              <text x={p.x} y={p.y + 4} textAnchor="middle">{text}</text>
            </g>
          );
        }
        if (n.kind === "lift") {
          return (
            <g key={n.id} className={cls}>
              <title>{n.label}</title>
              <rect x={p.x - 28} y={p.y - 15} width={56} height={30} rx={7} />
              <path className="glyph" d={`M${p.x - 19},${p.y - 2} l4,-5 l4,5z M${p.x - 19},${p.y + 2} l4,5 l4,-5z`} />
              <text x={p.x + 6} y={p.y + 4.5} textAnchor="middle">{fid}</text>
              {fid && pulse.has(fid) && <circle className="pulse" cx={p.x} cy={p.y} r={16} />}
            </g>
          );
        }
        if (n.kind === "street") {
          return (
            <g key={n.id} className={cls}>
              <rect x={p.x - 38} y={p.y - 14} width={76} height={28} rx={14} />
              <text x={p.x} y={p.y + 4.5} textAnchor="middle">{S.xray.street}</text>
            </g>
          );
        }
        const r = n.kind === "entrance" ? 6 : 3.2;
        return (
          <g key={n.id} className={cls}>
            <circle cx={p.x} cy={p.y} r={r} />
          </g>
        );
      })}
      {paths.flatMap((p) => Array.from({ length: DOTS }, (_, j) => (
        <circle key={`d-${p.label}-${j}`} r={5} className={`flow-dot route-${p.label}`} opacity={0} />
      )))}
    </svg>
  );
}
