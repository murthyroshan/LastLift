import * as THREE from "three";
import type { GraphEdge, GraphNode, StationGraph } from "../../../api";
import { layoutStation } from "../../../lib/stationLayout";

export const LEVEL_GAP = 3.4;      // world units between slabs (tall stations get less, see gapFor)
export const SLAB_DEPTH = 7;

export type NodePos = { node: GraphNode; p: THREE.Vector3; row: number; w: number };
export type Shaft = { id: string; fid: string; x: number; z: number; top: number; bottom: number; node: GraphNode; stagger: number };
export type Scene = {
  width: number;
  gap: number;                          // level spacing for this station
  rows: number;
  bandKind: GraphNode["kind"][];
  nodes: Map<string, NodePos>;
  shafts: Map<string, Shaft>;          // lift node id -> shaft
  edgeCurve: (e: GraphEdge) => THREE.Curve<THREE.Vector3> | null;
  baseEdges: GraphEdge[];               // two-way pairs once, lift-to-shaft legs included
  center: THREE.Vector3;
  size: THREE.Vector3;
};

/** World positions for a station graph. Rows from the shared layout become levels (street at the top); within a
 *  level, x follows the layout order and z spreads node kinds front to back so routes read in depth. A lift is a
 *  vertical shaft spanning the levels its lift edges touch; edges meet the shaft at the other end's level. */
export function buildScene(graph: StationGraph): Scene {
  const lay = layoutStation(graph);
  const maxRow = Math.max(...lay.rows.map((r) => r.length));
  const width = Math.min(46, Math.max(22, maxRow * 1.55));
  const gap = Math.max(2.3, Math.min(LEVEL_GAP, LEVEL_GAP * 7 / Math.max(7, lay.rows.length)));
  const nodes = new Map<string, NodePos>();
  const zOf = (n: GraphNode, i: number) =>
    n.kind === "platform" ? 1.9 : n.kind === "entrance" ? -1.9 : n.kind === "street" ? 0
      : n.kind === "lift" ? -0.6 : ((i % 3) - 1) * 1.25;
  lay.rows.forEach((row, ri) => row.forEach((n, i) => {
    const pl = lay.placed.get(n.id)!;
    nodes.set(n.id, { node: n, row: ri, w: pl.w * width, p: new THREE.Vector3((pl.t - 0.5) * width, -ri * gap, zOf(n, i)) });
  }));

  // shafts: every lift node spans the levels of the nodes its lift edges reach
  const shafts = new Map<string, Shaft>();
  for (const n of graph.nodes) {
    if (n.kind !== "lift") continue;
    const at = nodes.get(n.id);
    if (!at) continue;
    const ys = [at.p.y];
    for (const e of graph.edges) {
      if (e.source === n.id) { const o = nodes.get(e.target); if (o) ys.push(o.p.y); }
      if (e.target === n.id) { const o = nodes.get(e.source); if (o) ys.push(o.p.y); }
    }
    shafts.set(n.id, { id: n.id, fid: n.facility_id ?? n.id, x: at.p.x, z: at.p.z, top: Math.max(...ys) + 0.55,
      bottom: Math.min(...ys) - 0.35, node: n, stagger: 0 });
  }
  // labels sit above each shaft; neighbours closer than a label's width take turns stepping up
  const byTop = [...shafts.values()].sort((a, b) => a.x - b.x);
  byTop.forEach((s, i) => {
    const prev = byTop[i - 1];
    if (prev && Math.abs(prev.x - s.x) < 2.4 && Math.abs(prev.top - s.top) < 1.5) s.stagger = (prev.stagger + 1) % 3;
  });

  const point = (id: string, other: string): THREE.Vector3 | null => {
    const s = shafts.get(id);
    const o = nodes.get(other);
    if (s && o) return new THREE.Vector3(s.x, o.p.y, s.z);       // meet the shaft at the other end's level
    return nodes.get(id)?.p.clone() ?? null;
  };

  const edgeCurve = (e: GraphEdge): THREE.Curve<THREE.Vector3> | null => {
    const a = point(e.source, e.target), b = point(e.target, e.source);
    if (!a || !b) return null;
    if (Math.abs(a.y - b.y) < 0.01) {
      const mid = a.clone().lerp(b, 0.5);
      mid.y += Math.min(0.9, a.distanceTo(b) * 0.12);
      return new THREE.QuadraticBezierCurve3(a, mid, b);
    }
    const my = (a.y + b.y) / 2;
    return new THREE.CubicBezierCurve3(a, new THREE.Vector3(a.x, my, a.z), new THREE.Vector3(b.x, my, b.z), b);
  };

  const seen = new Map<string, GraphEdge>();
  for (const e of graph.edges) {
    const k = [e.source, e.target].sort().join("|");
    const prev = seen.get(k);
    if (!prev || (e.status === "closed" && prev.status !== "closed")) seen.set(k, e);
  }

  const box = new THREE.Box3();
  nodes.forEach((n) => box.expandByPoint(n.p));
  shafts.forEach((s) => { box.expandByPoint(new THREE.Vector3(s.x, s.top, s.z)); box.expandByPoint(new THREE.Vector3(s.x, s.bottom, s.z)); });
  box.expandByPoint(new THREE.Vector3(-width / 2 - 2, 0, -SLAB_DEPTH / 2));
  box.expandByPoint(new THREE.Vector3(width / 2 + 2, 0, SLAB_DEPTH / 2));
  return {
    width, gap, rows: lay.rows.length, bandKind: lay.bandKind, nodes, shafts, edgeCurve, baseEdges: [...seen.values()],
    center: box.getCenter(new THREE.Vector3()), size: box.getSize(new THREE.Vector3()),
  };
}

/** One continuous path through a route's edges (shaft rides included), for particles and the glowing tube. */
export function routePath(scene: Scene, edgeIds: string[], byId: Map<string, GraphEdge>): THREE.CurvePath<THREE.Vector3> | null {
  const path = new THREE.CurvePath<THREE.Vector3>();
  let last: THREE.Vector3 | null = null;
  for (const id of edgeIds) {
    const e = byId.get(id);
    const c = e && scene.edgeCurve(e);
    if (!c) continue;
    const start = c.getPoint(0);
    if (last && last.distanceTo(start) > 0.01) path.add(new THREE.LineCurve3(last.clone(), start));   // the ride inside a shaft
    path.add(c);
    last = c.getPoint(1);
  }
  return path.curves.length ? path : null;
}

/** Reads a colour token from the page (falls back to grey). */
export function cssColor(name: string, fallback = "#888888"): THREE.Color {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  try { return new THREE.Color(v || fallback); } catch { return new THREE.Color(fallback); }
}
