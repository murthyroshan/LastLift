import { useEffect, useMemo, useRef, useState } from "react";
import { getMap } from "../api";
import { href } from "../router";
import { S } from "../strings.en";

type St = { id: string; name: string; lat: number; lon: number; data: boolean; base: string | null; now: string | null;
  closed: string[]; new_last: boolean };
type View = "core" | "downtown" | "all";
type Box = { x: number; y: number; w: number; h: number };
const W = 1000, H = 720, PAD = 28;
const DOWNTOWN = { lat: [42.343, 42.369], lon: [-71.078, -71.043] };
const TWEEN_MS = 650;
const CENTRE = { lat: 42.356, lon: -71.062 }, R0 = 0.05, WARP = 0.55;

/** Every station at its coordinates (no map tiles), ride links in neutral ink, a glyph for each station's worst
 *  step-free state now; grey dots where MBTA publishes no station layout. The views zoom smoothly (instantly under
 *  reduced motion) and glyphs keep their size at every zoom. Mouse users get a hover card and can open a station;
 *  the station table on this page is the full text equivalent, so the drawing is decorative. */
export function NetworkMap({ initial = "core", focus }: { initial?: View; focus?: Set<string> }) {
  const [m, setM] = useState<{ stations: St[]; links: { a: string; b: string; rail: boolean }[] } | null>(null);
  const [view, setView] = useState<View>(initial);
  const [vb, setVb] = useState<Box | null>(null);
  const [tip, setTip] = useState<{ s: St; x: number; y: number } | null>(null);
  const stage = useRef<HTMLDivElement>(null);
  const anim = useRef(0);
  useEffect(() => { getMap().then(setM).catch(() => {}); }, []);

  // one projection for the whole network; views are boxes inside it. Distance from downtown is compressed
  // (a power law on the radius, like a transit diagram) so the dense centre is readable; directions are kept.
  const proj = useMemo(() => {
    if (!m) return null;
    const k = Math.cos(CENTRE.lat * Math.PI / 180);
    const warp = (lat: number, lon: number) => {
      const dx = (lon - CENTRE.lon) * k, dy = lat - CENTRE.lat;
      const r = Math.hypot(dx, dy), f = r ? Math.pow(r / R0, WARP) * R0 / r : 0;
      return { x: dx * f, y: dy * f };
    };
    const pts = m.stations.map((s) => warp(s.lat, s.lon));
    const x0 = Math.min(...pts.map((p) => p.x)), x1 = Math.max(...pts.map((p) => p.x));
    const y0 = Math.min(...pts.map((p) => p.y)), y1 = Math.max(...pts.map((p) => p.y));
    const s = Math.min((W - 2 * PAD) / (x1 - x0), (H - 2 * PAD) / (y1 - y0));
    const ox = (W - 2 * PAD - (x1 - x0) * s) / 2, oy = (H - 2 * PAD - (y1 - y0) * s) / 2;
    return (lat: number, lon: number) => {
      const q = warp(lat, lon);
      return { x: PAD + ox + (q.x - x0) * s, y: H - PAD - oy - (q.y - y0) * s };
    };
  }, [m]);

  const boxes = useMemo(() => {
    if (!m || !proj) return null;
    const fit = (pts: { x: number; y: number }[], pad: number): Box => {
      const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
      let x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
      const want = W / H;                                  // keep the frame's aspect so the figure never jumps
      if ((x1 - x0) / (y1 - y0) < want) { const d = ((y1 - y0) * want - (x1 - x0)) / 2; x0 -= d; x1 += d; }
      else { const d = ((x1 - x0) / want - (y1 - y0)) / 2; y0 -= d; y1 += d; }
      return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
    };
    const corners = (la: number[], lo: number[]) => [proj(la[0], lo[0]), proj(la[1], lo[1])];
    return {
      all: { x: 0, y: 0, w: W, h: H },
      core: fit(m.stations.filter((s) => s.data).map((s) => proj(s.lat, s.lon)), 14),
      downtown: fit(corners(DOWNTOWN.lat, DOWNTOWN.lon), 0),
    } as Record<View, Box>;
  }, [m, proj]);

  useEffect(() => {                                      // tween the viewBox between views
    if (!boxes) return;
    const to = boxes[view];
    const from = vb;
    cancelAnimationFrame(anim.current);
    if (!from || window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setVb(to); return; }
    const t0 = performance.now();
    const ease = (t: number) => 1 - Math.pow(1 - t, 3);
    const step = (now: number) => {
      const t = Math.min(1, (now - t0) / TWEEN_MS), e = ease(t);
      setVb({ x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e,
        w: from.w + (to.w - from.w) * e, h: from.h + (to.h - from.h) * e });
      if (t < 1) anim.current = requestAnimationFrame(step);
    };
    anim.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(anim.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boxes, view]);

  if (!m || !proj || !vb) return null;
  const at = new Map(m.stations.map((s) => [s.id, s]));
  const assessed = m.stations.filter((s) => s.data).length;
  const z = vb.w / W;                                    // screen-constant sizes
  const zoomed = z < 0.2;
  const labelled = (s: St) => s.data && (zoomed || (focus ? focus.has(s.id) : s.closed.length > 0 || s.new_last));

  const word = (s: St) => !s.data ? S.map.noData : s.now === "lost" ? S.k.lost : s.now === "one" ? S.k.one
    : s.now === "many" ? S.k.many : S.k.grade;
  const showTip = (s: St, e: React.MouseEvent) => {
    const r = stage.current?.getBoundingClientRect();
    if (r) setTip({ s, x: e.clientX - r.left, y: e.clientY - r.top });
  };

  const glyph = (s: St) => {
    const p = proj(s.lat, s.lon);
    const r = (zoomed ? 8 : 5.2) * z;
    const cls = !s.data ? "map-none" : s.now === "lost" ? "map-lost" : s.now === "one" ? "map-one" : s.now === "many" ? "map-many" : "map-grade";
    return (
      <g key={s.id} className={`${s.data ? "map-station link" : "map-station"} ${focus && !focus.has(s.id) ? "dim" : ""}`}
         onMouseEnter={(e) => showTip(s, e)} onMouseMove={(e) => showTip(s, e)} onMouseLeave={() => setTip(null)}
         onClick={s.data ? () => { window.location.hash = href(`/station/${s.id}`).slice(1); } : undefined}>
        <circle cx={p.x} cy={p.y} r={r * 2.2} className="map-hit" />
        {focus?.has(s.id) && <circle cx={p.x} cy={p.y} r={r * 2} className="map-focus" />}
        {s.closed.length > 0 && <circle cx={p.x} cy={p.y} r={r * 2.4} className="map-pulse" />}
        {s.new_last && <circle cx={p.x} cy={p.y} r={r * 1.9} className="map-halo" />}
        {!s.data ? <circle cx={p.x} cy={p.y} r={r * 0.42} className={cls} />
          : s.now === "one" ? <rect x={p.x - r * 0.85} y={p.y - r * 0.85} width={1.7 * r} height={1.7 * r} transform={`rotate(45 ${p.x} ${p.y})`} className={cls} />
          : s.now === "lost" ? <path d={`M${p.x - r},${p.y - r}L${p.x + r},${p.y + r}M${p.x + r},${p.y - r}L${p.x - r},${p.y + r}`} className={cls} />
          : <circle cx={p.x} cy={p.y} r={r * 0.9} className={cls} />}
      </g>
    );
  };
  return (
    <figure className="map-fig">
      <div className="map-toolbar">
        <p role="group" aria-label={S.map.viewLabel} className="map-views">
          {(["core", "downtown", "all"] as const).map((v) => (
            <button key={v} aria-pressed={view === v} onClick={() => setView(v)}>{S.map.views[v]}</button>
          ))}
        </p>
      </div>
      <div className="map-stage" ref={stage}>
        <svg viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`} className="map-svg" aria-hidden="true" focusable="false">
          {m.links.map((l) => {
            const a = at.get(l.a), b = at.get(l.b);
            if (!a || !b) return null;
            const p = proj(a.lat, a.lon), q = proj(b.lat, b.lon);
            return <line key={`${l.a}-${l.b}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} className={l.rail ? "map-rail" : "map-bus"} />;
          })}
          {m.stations.filter((s) => !s.data).map(glyph)}
          {m.stations.filter((s) => s.data && s.now !== "one").map(glyph)}
          {m.stations.filter((s) => s.data && s.now === "one").map(glyph)}
          {m.stations.filter(labelled).map((s) => {
            const p = proj(s.lat, s.lon);
            return <text key={`t-${s.id}`} x={p.x + 11 * z} y={p.y + 4.5 * z} className="map-label"
                         style={{ fontSize: `${13 * z}px`, strokeWidth: `${3 * z}px` }}>{s.name}</text>;
          })}
        </svg>
        {tip && (
          <div className="map-tip" style={{ left: tip.x, top: tip.y }} aria-hidden="true">
            <strong>{tip.s.name}</strong>
            <span className={`lg ${tip.s.data ? tip.s.now ?? "grade" : "none"}`}>
              {!tip.s.data ? "·" : tip.s.now === "lost" ? "✕" : tip.s.now === "one" ? "◆" : tip.s.now === "many" ? "●" : "○"}
            </span> {word(tip.s)}
            {tip.s.closed.length > 0 && <div className="muted">{S.map.tipClosed(tip.s.closed.join(", "))}</div>}
            {tip.s.new_last && <div className="muted">{S.map.tipNewLast}</div>}
          </div>
        )}
      </div>
      <figcaption>
        {S.map.label(m.stations.length, assessed)}{" "}
        {S.map.caption(assessed, m.stations.length - assessed, m.stations.filter((s) => s.closed.length).length,
          m.stations.filter((s) => s.new_last).length)}
        <ul className="map-legend">
          <li><span className="lg lost">✕</span> {S.k.lost}</li><li><span className="lg one">◆</span> {S.k.one}</li>
          <li><span className="lg many">●</span> {S.k.many}</li><li><span className="lg grade">○</span> {S.k.grade}</li>
          <li><span className="lg none">·</span> {S.map.noData}</li>
        </ul>
      </figcaption>
    </figure>
  );
}
