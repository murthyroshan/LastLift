import type { StationGraph } from "../api";

const BIG = 1_000_000;

/** Exact max-flow (Edmonds–Karp) on a station graph: every lift edge has capacity one, everything else is unbounded.
 *  With `without`, those lifts are removed first. Returns the number of lift-disjoint step-free routes, or null when
 *  the answer is unbounded (no lift is needed). Station graphs are small (tens to hundreds of edges), so BFS
 *  augmentation is instant; the same numbers come from FalkorDB's certified algo.maxFlow for the unchanged graph. */
export function liftRoutes(g: StationGraph, sources: string[], sinks: string[], without: Set<string> = new Set(),
  ignoreStatus = false): number | null {
  const idx = new Map<string, number>();
  const id = (n: string) => { if (!idx.has(n)) idx.set(n, idx.size); return idx.get(n)!; };
  const S = id("__S__"), T = id("__T__");
  type E = { to: number; cap: number; rev: number };
  const adj: E[][] = [];
  const add = (u: number, v: number, cap: number) => {
    while (adj.length <= Math.max(u, v)) adj.push([]);
    adj[u].push({ to: v, cap, rev: adj[v].length });
    adj[v].push({ to: u, cap: 0, rev: adj[u].length - 1 });
  };
  for (const e of g.edges) {
    if (!e.step_free) continue;
    if (e.kind === "lift" && e.facility_id && (without.has(e.facility_id) || (!ignoreStatus && e.status === "closed"))) continue;
    add(id(e.source), id(e.target), e.kind === "lift" ? 1 : BIG);
  }
  for (const s of sources) add(S, id(s), BIG);
  for (const t of sinks) add(id(t), T, BIG);
  while (adj.length < idx.size) adj.push([]);
  let flow = 0;
  for (;;) {
    const prev: ([number, number] | null)[] = new Array(adj.length).fill(null);
    const q = [S];
    prev[S] = [-1, -1];
    while (q.length && !prev[T]) {
      const u = q.shift()!;
      adj[u].forEach((e, i) => { if (e.cap > 0 && !prev[e.to]) { prev[e.to] = [u, i]; q.push(e.to); } });
    }
    if (!prev[T]) break;
    let push = Infinity;
    for (let v = T; v !== S; v = prev[v]![0]) push = Math.min(push, adj[prev[v]![0]][prev[v]![1]].cap);
    for (let v = T; v !== S; v = prev[v]![0]) {
      const [u, i] = prev[v]!;
      adj[u][i].cap -= push;
      adj[v][adj[u][i].rev].cap += push;
    }
    flow += push;
    if (flow >= BIG) return null;
  }
  return flow;
}

export type Cell = { platform: string; dir: "board" | "exit"; fid: string; base: number | null; after: number | null };

/** N-1: for every platform-direction and every working lift in the station, the routes left with that lift closed. */
export function nMinusOne(board: StationGraph, exit: StationGraph): { lifts: string[]; cells: Cell[] } {
  const lifts = [...new Set(board.nodes.filter((n) => n.kind === "lift" && n.facility_id && n.status !== "closed")
    .map((n) => n.facility_id!))].sort();
  const cells: Cell[] = [];
  for (const [dir, g] of [["board", board], ["exit", exit]] as const) {
    const streets = g.nodes.filter((n) => n.kind === "street").map((n) => n.id);
    for (const p of g.nodes.filter((n) => n.kind === "platform")) {
      const [src, dst] = dir === "board" ? [streets, [p.id]] : [[p.id], streets];
      const base = liftRoutes(g, src, dst);
      for (const fid of lifts) cells.push({ platform: p.id, dir, fid, base, after: base === null ? null : liftRoutes(g, src, dst, new Set([fid])) });
    }
  }
  return { lifts, cells };
}

/** Platform-directions of one station with no step-free route when exactly `closed` lifts are out (today's closures
 *  ignored): the replay of a past day on today's layout. */
export function lostWith(board: StationGraph, exit: StationGraph, closed: Set<string>) {
  const out: { platform: string; dir: "board" | "exit" }[] = [];
  for (const [dir, g] of [["board", board], ["exit", exit]] as const) {
    const streets = g.nodes.filter((n) => n.kind === "street").map((n) => n.id);
    for (const p of g.nodes.filter((n) => n.kind === "platform")) {
      const [src, dst] = dir === "board" ? [streets, [p.id]] : [[p.id], streets];
      const base = liftRoutes(g, src, dst, new Set(), true);
      if (base !== null && base > 0 && liftRoutes(g, src, dst, closed, true) === 0) out.push({ platform: p.id, dir });
    }
  }
  return out;
}
