import type { StationBundle, StationGraph } from "../api";
import { liftRoutes } from "./maxflow";

export type Change = { station: string; stationId: string; platform: string; name: string; dir: "board" | "exit";
  before: number; after: number; last: string[] };

/** Every platform-direction of a station whose lift-disjoint routes drop when `closed` lifts close, with the lifts
 *  that become the last one where a single route is left. Exact, in the browser, from the mirrored station graph. */
export function effects(b: StationBundle, closed: Set<string>): Change[] {
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
