// Mirror-first data access. The judged demo state is frozen, so the static mirror (built from the same tools
// by scripts/build_mirror.py) is the primary source: every core screen works with the API blocked. The live
// API is used for what only it can do: simulating a lift that is not mirrored, answering new questions, and the
// Live scope (the MBTA's current alerts, polled by the server), which is never mirrored.

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "";

/** demo = the frozen alert snapshot every judge sees (mirrored); live = current MBTA alerts (API only). */
export type Scope = "demo" | "live";
export type LiveStatus = {
  feed: string; source: "mbta_api" | "harvest"; age_s: number | null; stale: boolean; state_version: number;
  closed: string[]; alerts: number | null; last_ok_at: string | null; last_error: string | null;
};

export type Envelope<T = any> = {
  ok: boolean; tool: string; summary: string; data: T; entities: string[];
  evidence?: { query_ids: string[]; graph: string; ms: number };
  highlight?: { nodes: string[]; edges: string[] };
};

export type GraphNode = {
  id: string; kind: "street" | "entrance" | "area" | "gate" | "lift" | "platform"; label: string;
  rank: number | null; band: number | null; facility_id?: string; status?: string;
  last_lift?: string[]; stop_id?: string; k_board?: number | null; k_exit?: number | null; modelled?: boolean;
};
export type GraphEdge = { id: string; source: string; target: string; kind: "walk" | "gate" | "lift" | "step";
  step_free: boolean; facility_id?: string; status?: string };
export type ContractPlatform = { id: string; name: string; k_board: number | null; k_exit: number | null;
  k_board_base: number | null; k_exit_base: number | null; verdict: string };
export type StationGraph = {
  station: { id: string; name: string; closed: string[]; scenario: string | null };
  nodes: GraphNode[]; edges: GraphEdge[]; platforms: ContractPlatform[];
  routes: { platform_id: string; dir: string; label: string; edge_ids: string[]; lifts: string[]; text: string[] }[];
  receipt: { flow_ms: number; ms: number; graph: string };
};
export type StationBundle = { redundancy: Envelope; graph: { board: StationGraph; exit: StationGraph } };
export type WhatIfBundle = { station: string; whatif: Envelope; graph: { board?: StationGraph; exit?: StationGraph } };

async function json<T>(url: string, init?: RequestInit, timeoutMs = 8000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { ...init, signal: ctrl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return (await r.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

const mirror = <T,>(path: string) => json<T>(`${import.meta.env.BASE_URL}m/${path}`);

export const getClaims = () => json<Record<string, any>>(`${import.meta.env.BASE_URL}claims.json`);
export const getState = () => mirror<{ closures: Envelope; priority: Envelope; eval: Record<string, any> }>("state.json");
export const getStations = () =>
  mirror<{ id: string; name: string; platforms: number; lost: number; single: number; closed: string[] }[]>("stations.json");
export const getStation = (id: string) => mirror<StationBundle>(`station/${encodeURIComponent(id)}.json`);
export const getQueries = () => mirror<Record<string, string>>("queries.json");
export const getEvalRows = () => mirror<Record<string, string>[]>("eval.json");
export const getDisclaimers = () => mirror<Record<string, string>>("disclaimers.json");
export const getTicket = (fid: string) => mirror<Envelope>(`ticket/${encodeURIComponent(fid)}.json`);
export const getReroute = (stop: string) =>
  mirror<{ platform: any; exit: Envelope; board: Envelope }>(`reroute/${encodeURIComponent(stop)}.json`);
export const getReplayIndex = () =>
  json<{ id: string; question: string; source: string }[]>(`${import.meta.env.BASE_URL}replay/index.json`);
export const getReplay = (id: string) => json<any>(`${import.meta.env.BASE_URL}replay/${encodeURIComponent(id)}.json`);

const tool = <T = any,>(name: string, args: Record<string, unknown>) => json<Envelope<T>>(
  `${API_BASE}/v1/tools/${name}`,
  { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(args) }, 30000);
const view = (stationId: string, dir: string, scope: Scope, scenario?: string) => json<StationGraph>(
  `${API_BASE}/v1/stations/${encodeURIComponent(stationId)}/graph?dir=${dir}&scope=${scope}`
  + (scenario ? `&scenario=${encodeURIComponent(scenario)}` : ""), undefined, 30000);

export const getLiveStatus = () => json<LiveStatus>(`${API_BASE}/v1/live`);

/** Closures and repair priority for a scope; the evaluation summary is the same in both. */
export async function getStateFor(scope: Scope) {
  const demo = await getState();
  if (scope === "demo") return demo;
  const [closures, priority] = await Promise.all([
    tool("current_closures", { scope }), tool("repair_priority", { scope, limit: 200 })]);
  return { closures, priority, eval: demo.eval };
}

export async function getStationFor(id: string, scope: Scope): Promise<StationBundle> {
  if (scope === "demo") return getStation(id);
  const [redundancy, board, exit] = await Promise.all([
    tool("platform_redundancy", { station_id: id, scope }), view(id, "board", scope), view(id, "exit", scope)]);
  return { redundancy, graph: { board, exit } };
}

export const getTicketFor = (fid: string, scope: Scope) =>
  scope === "demo" ? getTicket(fid) : tool("draft_action", { facility_id: fid, scope });

export async function getRerouteFor(p: { stop_id: string; station_id: string }, scope: Scope) {
  if (scope === "demo") return getReroute(p.stop_id);
  const [exit, board] = await Promise.all([
    tool("step_free_route", { from_station: p.station_id, from_platform: p.stop_id, scope }),
    tool("step_free_route", { from_station: p.station_id, to_platform: p.stop_id, scope })]);
  return { platform: p, exit, board };
}

/** A what-if: the mirror for the story lifts (demo), otherwise the live API (copy-on-write in FalkorDB). */
export async function getWhatIf(stationId: string, fid: string, live: boolean,
                                scope: Scope = "demo"): Promise<WhatIfBundle | null> {
  if (scope === "demo") {
    try {
      return await mirror<WhatIfBundle>(`whatif/${encodeURIComponent(fid)}.json`);
    } catch {
      if (!live) return null;
    }
  }
  const whatif = await tool("what_if_close", { facility_ids: [fid], scope });
  const copy = whatif.data?.copy;
  if (!copy) return { station: stationId, whatif, graph: {} };
  const [board, exit] = await Promise.all([view(stationId, "board", scope, copy), view(stationId, "exit", scope, copy)]);
  return { station: stationId, whatif, graph: { board, exit } };
}

/** Live health: resolves to true once the API answers /healthz (Render's free tier sleeps when idle). */
export async function pingLive(timeoutMs = 6000): Promise<boolean> {
  try {
    await json(`${API_BASE}/healthz`, undefined, timeoutMs);
    return true;
  } catch {
    return false;
  }
}

/** Ask the live agent; events arrive one by one (server-sent events). */
export function askLive(question: string, onEvent: (e: any) => void, scope: Scope = "demo"): () => void {
  const src = new EventSource(`${API_BASE}/api/ask?q=${encodeURIComponent(question)}&scope=${scope}`);
  const kinds = ["start", "tool_call", "tool_result", "error", "grounding", "answer", "done"];
  for (const k of kinds) {
    src.addEventListener(k, (m) => {
      const ev = JSON.parse((m as MessageEvent).data);
      onEvent(ev);
      if (ev.type === "done") src.close();
    });
  }
  src.onerror = () => {
    onEvent({ type: "error", stage: "network", message: "connection lost" });
    onEvent({ type: "done" });
    src.close();
  };
  return () => src.close();
}
