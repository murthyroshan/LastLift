// Mirror-first data access. The judged demo state is frozen, so the static mirror (built from the same tools
// by scripts/build_mirror.py) is the primary source: every core screen works with the API blocked. The live
// API is used for what only it can do: simulating a lift that is not mirrored, and answering new questions.

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "";

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

/** A what-if: the mirror for the story lifts, otherwise the live API (copy-on-write in FalkorDB). */
export async function getWhatIf(stationId: string, fid: string, live: boolean): Promise<WhatIfBundle | null> {
  try {
    return await mirror<WhatIfBundle>(`whatif/${encodeURIComponent(fid)}.json`);
  } catch {
    if (!live) return null;
  }
  const whatif = await json<Envelope>(`${API_BASE}/v1/tools/what_if_close`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ facility_ids: [fid] }),
  }, 30000);
  const copy = whatif.data?.copy;
  if (!copy) return { station: stationId, whatif, graph: {} };
  const view = (dir: string) => json<StationGraph>(
    `${API_BASE}/v1/stations/${encodeURIComponent(stationId)}/graph?dir=${dir}&scenario=${encodeURIComponent(copy)}`,
    undefined, 30000);
  const [board, exit] = await Promise.all([view("board"), view("exit")]);
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
export function askLive(question: string, onEvent: (e: any) => void): () => void {
  const src = new EventSource(`${API_BASE}/api/ask?q=${encodeURIComponent(question)}`);
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
