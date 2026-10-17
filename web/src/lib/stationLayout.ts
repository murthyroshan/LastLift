import type { GraphNode, StationGraph } from "../api";

const ORDER = { street: 0, entrance: 1, gate: 2, area: 3, lift: 4, platform: 5 } as const;
export const WEIGHT = { street: 2, entrance: 1, gate: 0.55, area: 0.55, lift: 1.5, platform: 2.6 } as const;
const PRIORITY = ["street", "platform", "lift", "entrance", "gate", "area"] as const;

export type Placed = { node: GraphNode; row: number; t: number; w: number };  // t, w: centre and width as a share of the row
export type StationLayout = { rows: GraphNode[][]; placed: Map<string, Placed>; bandKind: GraphNode["kind"][] };

/** One row per step from the street (the contract's rank); within a row, nodes are ordered by barycentre sweeps
 *  (down, then up, six times) to cut edge crossings, and given widths by kind. Deterministic: ties break on id.
 *  Shared by the plan drawing and the 3D model so both show the same arrangement. */
export function layoutStation(graph: StationGraph): StationLayout {
  const maxRank = Math.max(0, ...graph.nodes.map((n) => n.rank ?? 0));
  const rowsMap = new Map<number, GraphNode[]>();
  for (const n of graph.nodes) {
    const r = n.rank ?? maxRank + 1;                           // nodes with no step-free link go to the bottom
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
  const order = new Map<string, number>();
  rows.forEach((row) => row.forEach((n, i) => order.set(n.id, (i + 0.5) / row.length)));
  const sweep = (range: number[]) => {
    for (const ri of range) {
      const inRow = new Set(rows[ri].map((x) => x.id));
      const bc = new Map(rows[ri].map((n) => {
        const ns = [...(nbr.get(n.id) ?? [])].filter((m) => order.has(m) && !inRow.has(m));
        return [n.id, ns.length ? ns.reduce((s, m) => s + order.get(m)!, 0) / ns.length : order.get(n.id)!];
      }));
      rows[ri].sort((p, q) => bc.get(p.id)! - bc.get(q.id)! || p.id.localeCompare(q.id));
      rows[ri].forEach((n, i) => order.set(n.id, (i + 0.5) / rows[ri].length));
    }
  };
  const down = rows.map((_, i) => i).slice(1), up = rows.map((_, i) => i).reverse().slice(1);
  for (let it = 0; it < 6; it++) { sweep(down); sweep(up); }

  const placed = new Map<string, Placed>();
  rows.forEach((row, ri) => {
    const total = row.reduce((s, n) => s + WEIGHT[n.kind], 0);
    let x = 0;
    for (const n of row) {
      const w = WEIGHT[n.kind] / total;
      placed.set(n.id, { node: n, row: ri, t: x + w / 2, w });
      x += w;
    }
  });
  const bandKind = rows.map((row) => PRIORITY.find((k) => row.some((n) => n.kind === k)) ?? "area");
  return { rows, placed, bandKind };
}

/** A platform's short name: the station's own name dropped from the front. */
export const shortName = (label: string, station: string) =>
  label.startsWith(`${station} `) ? label.slice(station.length + 1) : label;
