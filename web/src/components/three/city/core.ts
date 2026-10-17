import { useEffect, useState } from "react";
import { getClaims, getContingency, getMap, getStateFor, getStationFor, getStations, type StationBundle } from "../../../api";

/* ------------------------------------------------------------------ projection */

/** Downtown Boston is the origin; x east, z south, y up. One degree of latitude = K scene units. */
export const ORIGIN = { lat: 42.356, lon: -71.062 };
export const K = 110;
const COS = Math.cos((ORIGIN.lat * Math.PI) / 180);
export function project(lat: number, lon: number): [number, number] {
  return [(lon - ORIGIN.lon) * COS * K, -(lat - ORIGIN.lat) * K];
}

/* ------------------------------------------------------------------ scroll + motion clock */

/**
 * One module-level store, read inside the render loop (no React re-render per scroll).
 * p: story position, 0 = first step centred, 4 = last step centred (fractional between).
 * t: the motion clock. It only advances while the reader is scrolling, for four seconds after,
 *    and for four seconds after load, so nothing moves on its own for longer than five seconds.
 */
export const story = {
  p: 0,
  pSmooth: 0,
  t: 0,
  lastInput: 0,
  mountedAt: 0,
  reduced: false,
  dark: true,
  enteredStep: [0, 0, 0, 0, 0] as number[],   // motion-clock time at which each step was entered
  active: 0,
  film: false,                                // offline film render: exact frames, no smoothing, centred framing
};

export const MOTION_WINDOW = 4;

/** Development switches (?ci=noreflect,nofx,nodof,...) to profile the scene on slow GPUs. */
export const flags = new Set((typeof location !== "undefined" ? new URLSearchParams(location.search).get("ci") ?? "" : "").split(","));                  // seconds of motion after the last input

export function advanceClock(dt: number, now: number) {
  const since = Math.min(now - story.lastInput, now - story.mountedAt);
  if (!story.reduced && since < MOTION_WINDOW) story.t += dt;
}

export const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v));
export const smooth = (a: number, b: number, v: number) => {
  const x = clamp((v - a) / (b - a));
  return x * x * (3 - 2 * x);
};

/* ------------------------------------------------------------------ data */

export type CityStation = {
  id: string; name: string; lat: number; lon: number; x: number; z: number;
  data: boolean; now: string | null; closed: string[]; newLast: boolean; single: number; lost: number;
};
export type CityData = {
  stations: CityStation[];
  byId: Map<string, CityStation>;
  links: { a: CityStation; b: CityStation; rail: boolean }[];
  claims: Record<string, any>;
  focus: { station: CityStation; fid: string; closed: string[]; platforms: number } | null;
  arc: { fid: string; station: CityStation; targets: CityStation[]; od: number } | null;
  bundle: StationBundle | null;
};

export function useCityData(): CityData | null {
  const [d, setD] = useState<CityData | null>(null);
  useEffect(() => {
    let live = true;
    // the mirror's fetch gives up after a few seconds; a busy host should not leave the scene empty, so retry
    const retry = async <T,>(f: () => Promise<T>, n = 4): Promise<T> => {
      for (let i = 0; ; i++) {
        try { return await f(); } catch (e) { if (i >= n || !live) throw e; await new Promise((r) => setTimeout(r, 600 * (i + 1))); }
      }
    };
    (async () => {
      const [m, st, claims, state, cont] = await Promise.all([
        retry(getMap), retry(getStations), retry(getClaims), retry(() => getStateFor("demo")), retry(() => getContingency("demo"))]);
      const counts = new Map(st.map((s) => [s.id, s]));
      const stations: CityStation[] = m.stations.map((s: any) => {
        const [x, z] = project(s.lat, s.lon);
        return { id: s.id, name: s.name, lat: s.lat, lon: s.lon, x, z, data: !!s.data, now: s.now ?? null,
          closed: s.closed ?? [], newLast: !!s.new_last, single: counts.get(s.id)?.single ?? 0, lost: counts.get(s.id)?.lost ?? 0 };
      });
      const byId = new Map(stations.map((s) => [s.id, s]));
      const links = m.links.flatMap((l: any) => {
        const a = byId.get(l.a), b = byId.get(l.b);
        return a && b ? [{ a, b, rail: !!l.rail }] : [];
      });
      const nl = state.closures.data?.newly_last_lift?.[0];
      const fs = nl ? byId.get(nl.station_id) : undefined;
      const focus = nl && fs ? {
        station: fs, fid: String(nl.facility_id), closed: counts.get(fs.id)?.closed ?? fs.closed,
        platforms: new Set((nl.now_sole_link_for ?? []).map((x: string) => x.split(" ")[0])).size,
      } : null;
      const spof: any[] = cont.network_spof ?? [];
      const pick = spof.find((x) => x.station_id === "place-davis") ?? spof[0];
      const as = pick ? byId.get(pick.station_id) : undefined;
      const arc = pick && as ? {
        fid: String(pick.facility_id), station: as, od: pick.od_cut,
        targets: (pick.dominates_for as string[]).filter((s) => s !== pick.station_id).flatMap((s) => byId.get(s) ?? []),
      } : null;
      const bundle = focus ? await retry(() => getStationFor(focus.station.id, "demo")).catch(() => null) : null;
      if (live) setD({ stations, byId, links, claims, focus, arc, bundle });
    })().catch(() => {});
    return () => { live = false; };
  }, []);
  return d;
}

/* ------------------------------------------------------------------ palette */

export type Palette = {
  sky: string; fog: string; ground: string; grid: string; city: [number, number, number];
  rail: [number, number, number]; one: [number, number, number]; lost: [number, number, number];
  many: [number, number, number]; grade: [number, number, number]; none: [number, number, number];
  gold: [number, number, number];
};

/** HDR colours (values above one bloom). Dark: night. Light scheme: a paler dusk. */
export function palette(dark: boolean): Palette {
  return dark ? {
    sky: "#05070c", fog: "#070a12", ground: "#04060a", grid: "#3b4a66", city: [1.0, 0.72, 0.42],
    rail: [1.0, 0.92, 0.8], one: [2.3, 1.25, 0.25], lost: [2.5, 0.42, 0.32], many: [0.45, 1.05, 2.5],
    grade: [1.15, 1.2, 1.3], none: [0.32, 0.35, 0.42], gold: [2.9, 1.85, 0.35],
  } : {
    sky: "#2b3557", fog: "#3a4568", ground: "#1b2238", grid: "#8aa0c8", city: [1.0, 0.8, 0.6],
    rail: [1.1, 1.05, 1.0], one: [2.2, 1.25, 0.3], lost: [2.3, 0.5, 0.4], many: [0.55, 1.1, 2.3],
    grade: [1.2, 1.25, 1.35], none: [0.5, 0.55, 0.66], gold: [2.7, 1.8, 0.45],
  };
}

/** A small deterministic PRNG so the city lights are the same on every load. */
export function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
