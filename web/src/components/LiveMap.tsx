import { useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre finds its worker next to its own module; bundling moves it, so hand Vite's bundled worker URL over.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ArcLayer, ColumnLayer, LineLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { getContingency, getMap, getStations } from "../api";
import { href } from "../router";

export type Camera = { lng: number; lat: number; zoom: number; pitch: number; bearing: number };
type MapStation = { id: string; name: string; lat: number; lon: number; data: boolean; now: string | null;
  closed: string[]; new_last: boolean };
type Row = MapStation & { single: number; lost: number; platforms: number };
type RGBA = [number, number, number, number];

export const CAMERAS: Record<string, Camera> = {
  overview: { lng: -71.075, lat: 42.335, zoom: 10.6, pitch: 52, bearing: -18 },
  downtown: { lng: -71.062, lat: 42.355, zoom: 13.2, pitch: 58, bearing: 24 },
  alewife: { lng: -71.142, lat: 42.396, zoom: 14.6, pitch: 62, bearing: -30 },
  davis: { lng: -71.105, lat: 42.37, zoom: 11.4, pitch: 48, bearing: 10 },
  flat: { lng: -71.075, lat: 42.335, zoom: 10.4, pitch: 0, bearing: 0 },
};

const STYLE = {
  dark: "https://basemaps.cartocdn.com/gl/dark-matter-nolabels-gl-style/style.json",
  light: "https://basemaps.cartocdn.com/gl/positron-nolabels-gl-style/style.json",
};

/** Reads a colour token from the page so the map uses the same palette as everything else. */
function token(name: string, alpha = 255): RGBA {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const m = v.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (!m) return [128, 128, 128, alpha];
  const h = m[1].length === 3 ? m[1].split("").map((c) => c + c).join("") : m[1];
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), alpha];
}

maplibregl.setWorkerUrl(workerUrl);

const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const dark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;

type Props = {
  camera?: Camera;
  /** stations to light up; everything else dims */
  highlight?: Set<string> | null;
  /** draw the journeys a lift cuts: arcs from its station to every station whose journeys it dominates */
  arcLifts?: string[];
  /** 0..1, how tall the single-lift columns stand */
  rise?: number;
  /** label these stations on the map */
  labels?: string[];
  interactive?: boolean;
  /** column size multiplier (smaller when the camera is close) */
  scale?: number;
  /** leave the left part of the frame for overlaid text */
  padLeft?: boolean;
  className?: string;
};

/** The network on a real basemap (MapLibre + deck.gl): a column per station whose height is the number of
 *  platforms hanging on one lift, pulses where a lift is closed, and arcs for the journeys a lift alone carries.
 *  Decorative for assistive technology; every fact is in the surrounding text and the station table. */
export function LiveMap({ camera = CAMERAS.overview, highlight = null, arcLifts = [], rise = 1, labels = [],
  interactive = true, padLeft = false, scale = 1, className = "" }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const overlay = useRef<MapboxOverlay | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [links, setLinks] = useState<{ a: string; b: string; rail: boolean }[]>([]);
  const [spof, setSpof] = useState<{ facility_id: string; station_id: string; dominates_for: string[] }[]>([]);
  const [ready, setReady] = useState(false);
  const [pulse, setPulse] = useState(0);

  useEffect(() => {
    Promise.all([getMap(), getStations(), getContingency("demo").catch(() => null)]).then(([m, st, c]) => {
      const by = new Map(st.map((s) => [s.id, s]));
      setRows((m.stations as MapStation[]).map((s) => ({ ...s, single: by.get(s.id)?.single ?? 0, lost: by.get(s.id)?.lost ?? 0,
        platforms: by.get(s.id)?.platforms ?? 0 })));
      setLinks(m.links);
      setSpof(c?.network_spof ?? []);
    }).catch(() => {});
  }, []);

  useEffect(() => {                                   // create the map once
    if (!box.current) return;
    const m = new maplibregl.Map({
      container: box.current, style: dark() ? STYLE.dark : STYLE.light,
      center: [camera.lng, camera.lat], zoom: camera.zoom, pitch: camera.pitch, bearing: camera.bearing,
      interactive, attributionControl: { compact: true }, maxPitch: 75, fadeDuration: 0,
    });
    if (interactive) m.scrollZoom.disable();          // never hijack page scrolling; +/- and drag still work
    if (interactive) m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    const o = new MapboxOverlay({ interleaved: false, layers: [] });
    m.addControl(o as unknown as maplibregl.IControl);
    // The drawing is decorative (the page's text and tables carry every fact): hide the canvas itself from assistive
    // technology and the tab order, but keep MapLibre's labelled zoom buttons and attribution reachable.
    const canvas = m.getCanvas();
    canvas.setAttribute("aria-hidden", "true");
    canvas.setAttribute("tabindex", "-1");
    canvas.removeAttribute("aria-label");
    canvas.removeAttribute("role");
    m.on("load", () => setReady(true));
    map.current = m; overlay.current = o;
    return () => { m.remove(); map.current = null; overlay.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {                                   // fly to the requested camera
    const m = map.current;
    if (!m) return;
    const w = m.getContainer().clientWidth;
    const left = padLeft && w > 1024 ? Math.round(w * 0.4) : 0;     // keep the subject clear of the story panel
    m.flyTo({ center: [camera.lng, camera.lat], zoom: camera.zoom, pitch: camera.pitch, bearing: camera.bearing,
      padding: { left, top: 0, right: 0, bottom: 0 }, duration: reduced() ? 0 : 2200, essential: false, curve: 1.4 });
  }, [camera, padLeft]);

  const closedHere = useMemo(() => rows.filter((r) => r.closed.length > 0), [rows]);
  useEffect(() => {                                   // three pulses where a lift is closed (stops well under 5 s)
    if (!ready || !closedHere.length || reduced()) return;
    const t0 = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = (now - t0) / 1000;
      setPulse(t < 3 ? t % 1 : 0);
      if (t < 3) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [ready, closedHere.length]);

  const arcs = useMemo(() => {
    const at = new Map(rows.map((r) => [r.id, r]));
    return spof.filter((x) => arcLifts.includes(x.facility_id)).flatMap((x) => {
      const a = at.get(x.station_id);
      return a ? x.dominates_for.filter((s) => s !== x.station_id).flatMap((s) => {
        const b = at.get(s);
        return b ? [{ from: [a.lon, a.lat], to: [b.lon, b.lat], id: `${x.facility_id}-${s}` }] : [];
      }) : [];
    });
  }, [rows, spof, arcLifts]);

  useEffect(() => {
    const o = overlay.current;
    if (!o || !rows.length) return;
    const c = { k0: token("--k0"), k1: token("--k1-fill"), k2: token("--k2"), muted: token("--muted", 150),
      fg: token("--fg"), unknown: token("--unknown", 170), last: token("--lastlift") };
    const at = new Map(rows.map((r) => [r.id, r]));
    const dim = (id: string) => (highlight && !highlight.has(id) ? 0.18 : 1);
    const colour = (r: Row): RGBA => {
      const base = r.now === "lost" ? c.k0 : r.single > 0 ? c.k1 : r.now === "many" ? c.k2 : c.muted;
      return [base[0], base[1], base[2], Math.round(235 * dim(r.id))];
    };
    const data = rows.filter((r) => r.data);
    const layers = [
      new LineLayer({
        id: "links", data: links.filter((l) => at.has(l.a) && at.has(l.b)),
        getSourcePosition: (l: any) => [at.get(l.a)!.lon, at.get(l.a)!.lat],
        getTargetPosition: (l: any) => [at.get(l.b)!.lon, at.get(l.b)!.lat],
        getColor: (l: any) => (l.rail ? [c.fg[0], c.fg[1], c.fg[2], 70] : [c.fg[0], c.fg[1], c.fg[2], 28]),
        getWidth: (l: any) => (l.rail ? 2 : 1), widthUnits: "pixels",
      }),
      new ScatterplotLayer({
        id: "nodata", data: rows.filter((r) => !r.data), getPosition: (r: Row) => [r.lon, r.lat],
        getRadius: 2.2, radiusUnits: "pixels", getFillColor: c.unknown,
      }),
      new ScatterplotLayer({
        id: "base", data, getPosition: (r: Row) => [r.lon, r.lat], getRadius: 5, radiusUnits: "pixels",
        getFillColor: colour, stroked: true, getLineColor: [0, 0, 0, 160], lineWidthUnits: "pixels", getLineWidth: 1,
        pickable: true, updateTriggers: { getFillColor: [highlight] },
      }),
      new ColumnLayer({
        id: "columns", data: data.filter((r) => r.single > 0 || r.lost > 0), diskResolution: 24, radius: 110 * scale,
        extruded: true, getPosition: (r: Row) => [r.lon, r.lat], getElevation: (r: Row) => (r.single + r.lost * 2),
        elevationScale: 380 * rise * scale, getFillColor: colour, pickable: true,
        material: { ambient: 0.55, diffuse: 0.6, shininess: 40, specularColor: [255, 230, 180] },
        transitions: reduced() ? undefined : { elevationScale: { duration: 1400, easing: (t: number) => 1 - Math.pow(1 - t, 3) } },
        updateTriggers: { getFillColor: [highlight] },
      }),
      new ScatterplotLayer({
        id: "pulse", data: pulse ? closedHere : [], getPosition: (r: Row) => [r.lon, r.lat],
        getRadius: 8 + 26 * pulse, radiusUnits: "pixels", stroked: true, filled: false,
        getLineColor: [c.k0[0], c.k0[1], c.k0[2], Math.round(230 * (1 - pulse))], lineWidthUnits: "pixels", getLineWidth: 2,
        updateTriggers: { getRadius: pulse, getLineColor: pulse },
      }),
      new ScatterplotLayer({
        id: "lastlift", data: data.filter((r) => r.new_last), getPosition: (r: Row) => [r.lon, r.lat],
        getRadius: 13, radiusUnits: "pixels", stroked: true, filled: false, getLineColor: c.last,
        lineWidthUnits: "pixels", getLineWidth: 2.5,
      }),
      new ArcLayer({
        id: "arcs", data: arcs, getSourcePosition: (a: any) => a.from, getTargetPosition: (a: any) => a.to,
        getSourceColor: [c.k0[0], c.k0[1], c.k0[2], 220], getTargetColor: [c.k1[0], c.k1[1], c.k1[2], 200],
        getWidth: 1.8, widthUnits: "pixels", getHeight: 0.35, greatCircle: false,
        transitions: reduced() ? undefined : { getTargetPosition: { duration: 1600, enter: (v: any) => v } },
      }),
      new TextLayer({
        id: "labels", data: data.filter((r) => labels.includes(r.id)), getPosition: (r: Row) => [r.lon, r.lat],
        getText: (r: Row) => r.name, getSize: 14, getColor: c.fg, getPixelOffset: [0, -22], fontWeight: 700,
        fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif", outlineWidth: 4,
        outlineColor: dark() ? [10, 13, 18, 255] : [255, 255, 255, 255], fontSettings: { sdf: true },
        billboard: true, characterSet: "auto",
      }),
    ];
    o.setProps({
      layers,
      getTooltip: interactive ? ({ object }: any) => object && object.name ? {
        html: `<strong>${object.name}</strong><br/>${object.single ? `${object.single} single-lift platform${object.single > 1 ? "s" : ""}` : "no single-lift platform"}${object.closed?.length ? `<br/>closed: lift ${object.closed.join(", ")}` : ""}`,
        className: "deck-tip",
      } : null : undefined,
      onClick: interactive ? ({ object }: any) => {
        if (object?.data) window.location.hash = href(`/station/${object.id}`).slice(1);
      } : undefined,
    } as any);
  }, [rows, links, highlight, arcs, rise, labels, pulse, closedHere, interactive, scale]);

  return <div ref={box} className={`livemap ${className}`} />;
}
