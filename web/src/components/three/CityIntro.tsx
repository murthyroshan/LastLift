import { useEffect, useRef, useState } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { PerformanceMonitor } from "@react-three/drei";
import { MotionConfig, motion } from "framer-motion";
import * as THREE from "three";
import { MOTION_WINDOW, palette, story, useCityData, type CityData } from "./city/core";
import { Scene } from "./city/Scene";
import "./cityintro.css";
import { realGpu } from "../../lib/gpu";

/* User-facing copy. No digits in literals: every number comes from the data. */
const COPY = {
  label: "The story of one closure, in five steps over the network",
  skip: "Skip the story",
  rail: ["The count", "Today", "The pattern", "The network", "The proof"],
  railLabel: "Story steps",
  goTo: (name: string) => `Go to: ${name}`,
  eyebrow: "MBTA open data · FalkorDB max-flow",
  title: "Find the last lift before it fails.",
  countOf: (a: number, b: number) => `${a} of ${b}`,
  countText: "step-free platforms in Boston's MBTA station data hang on a single lift.",
  scroll: "Scroll to follow one closure through the network",
  s1eyebrow: (station: string) => `Today · ${station}`,
  s1title: "One lift is closed. Another has just become the last one.",
  s1body: (station: string, closed: string, fid: string, n: number) =>
    `At ${station}, lift ${closed} is closed in the alert feed. That leaves lift ${fid} as the only step-free link for ${n} platforms. One more failure, and riders who need a lift cannot get on or off there.`,
  s1stat: (fid: string) => `platforms now depend on lift ${fid} alone`,
  closedTag: (f: string) => `Lift ${f} closed`,
  lastTag: (f: string) => `Lift ${f}: now the last lift`,
  s2eyebrow: "The pattern",
  s2title: "Counting lifts is not enough.",
  s2body: (platforms: number, stations: number, naive: number) =>
    `${platforms} platforms at ${stations} stations hang on a single lift; each pillar rises with how many. ${naive} of those platforms are at stations that have two or more lifts. What matters is which lift lies on which route, and only a maximum flow through the station's graph sees that.`,
  s2stat: "single-lift platforms at stations with two or more lifts",
  s3eyebrow: "The network",
  s3title: "Some lifts carry the whole network.",
  s3body: (net: number, fid: string, station: string, od: number, total: number) =>
    `Riders can sometimes take a train to another station and come back. But ${net} lifts each cut a whole station off from the step-free network. Lift ${fid} at ${station} alone carries ${od} of the ${total} step-free journeys between stations: every arc is one of them.`,
  s3stat: (fid: string) => `journeys carried by lift ${fid} alone`,
  arcTag: (fid: string, station: string) => `Lift ${fid} · ${station}`,
  s4eyebrow: "The proof",
  s4title: "Every number is proved, not estimated.",
  s4body: (ok: number, calls: number, station: string) =>
    `Each count is a maximum flow computed inside FalkorDB, then checked by an independent proof: ${ok} of ${calls} calls certified, with an exact repair wherever the database's answer was wrong. Under the street is ${station} itself, drawn from its published layout: the gold shaft is the lift everyone now depends on.`,
  s4stat: "FalkorDB max-flow calls certified",
  open: (station: string) => `Open ${station}`,
  network: "See the whole network",
  street: "Street",
  lift: (f: string) => `Lift ${f}`,
};

const media = (q: string) => typeof window !== "undefined" && window.matchMedia(q).matches;

/** Counts up once (instant under reduced motion). */
function useCount(target: number | undefined, ms = 1600) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (target == null) return;
    if (media("(prefers-reduced-motion: reduce)")) { setV(target); return; }
    const t0 = performance.now();
    let raf = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - t0) / ms);
      setV(Math.round(target * (1 - Math.pow(1 - t, 4))));
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

const reveal = {
  initial: { opacity: 0, y: 36 },
  whileInView: { opacity: 1, y: 0 },
  viewport: { amount: 0.35, once: false },
  transition: { duration: 0.9, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] },
};

/** The cinematic opening: one WebGL scene of the network at night, flown through by scrolling. Every fact is in the
 *  text; the canvas is decorative. Under reduced motion the camera cuts between still framings. */
/** Renders on demand: frames only while the reader scrolls, for the short motion window after, and until the camera
 *  settles. An idle page draws nothing, which saves battery and keeps slow machines responsive. */
function Pump() {
  const invalidate = useThree((st) => st.invalidate);
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const now = performance.now() / 1000;
      const since = Math.min(now - story.lastInput, now - story.mountedAt);
      const settling = Math.abs(story.pSmooth - story.p) > 1e-3;
      if (settling || (!story.reduced && since < MOTION_WINDOW + 0.5)) invalidate();
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    invalidate();
    return () => cancelAnimationFrame(raf);
  }, [invalidate]);
  return null;
}

export function CityIntro() {
  const data = useCityData();
  const [dark, setDark] = useState(() => media("(prefers-color-scheme: dark)"));
  const [active, setActive] = useState(0);
  const [onScreen, setOnScreen] = useState(true);
  const [dpr, setDpr] = useState(1.5);
  const root = useRef<HTMLElement>(null);
  const steps = useRef<(HTMLElement | null)[]>([]);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const rq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => { setDark(mq.matches); story.dark = mq.matches; story.reduced = rq.matches; };
    sync();
    mq.addEventListener("change", sync); rq.addEventListener("change", sync);
    const now = performance.now() / 1000;
    story.mountedAt = now; story.lastInput = now; story.t = 0; story.p = 0; story.pSmooth = 0; story.active = 0;
    const onScroll = () => {
      const c = window.innerHeight / 2;
      const centres = steps.current.map((el) => {
        if (!el) return 0;
        const panel = el.querySelector<HTMLElement>("[data-anchor]") ?? el;
        const r = panel.getBoundingClientRect();
        return r.top + r.height / 2;
      });
      let p = 0;
      if (c <= centres[0]) p = 0;
      else if (c >= centres[centres.length - 1]) p = centres.length - 1;
      else for (let i = 0; i < centres.length - 1; i++) {
        if (c >= centres[i] && c < centres[i + 1]) { p = i + (c - centres[i]) / (centres[i + 1] - centres[i]); break; }
      }
      story.p = p;
      story.lastInput = performance.now() / 1000;
      const a = Math.round(p);
      if (a !== story.active) { story.active = a; story.enteredStep[a] = story.t; setActive(a); }
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    const io = new IntersectionObserver(([e]) => setOnScreen(e.isIntersecting), { rootMargin: "100px" });
    if (root.current) io.observe(root.current);
    return () => {
      window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll);
      mq.removeEventListener("change", sync); rq.removeEventListener("change", sync); io.disconnect();
    };
  }, [data]);

  const claims = data?.claims;
  const count = useCount(claims?.platforms_single_lift);
  const pal = palette(dark);
  const f = data?.focus;
  const arc = data?.arc;
  const singleStations = data ? data.stations.filter((s) => s.single > 0).length : 0;
  const go = (i: number) => steps.current[i]?.scrollIntoView({ behavior: media("(prefers-reduced-motion: reduce)") ? "auto" : "smooth", block: "center" });

  return (
    <MotionConfig reducedMotion="user">
      <section ref={root} className={`ci ${dark ? "ci-dark" : "ci-dusk"}`} aria-label={COPY.label}>
        <a className="ci-skip" href="#ci-end">{COPY.skip}</a>
        <div className="ci-stage">
          <div className="ci-canvas" aria-hidden="true">
            {data && realGpu() && (
              <Canvas frameloop={onScreen ? "demand" : "never"} dpr={dpr}
                      camera={{ fov: 38, near: 0.1, far: 5000, position: [30, 17, 52] }}
                      gl={{ antialias: false, powerPreference: "high-performance", toneMapping: THREE.NoToneMapping }}>
                <Pump />
                <PerformanceMonitor onDecline={() => setDpr(1)} onIncline={() => setDpr(1.5)} flipflops={3} />
                <Scene data={data as CityData} pal={pal} dark={dark} copy={{
                  closedTag: COPY.closedTag(f?.closed.join(", ") ?? ""), lastTag: COPY.lastTag(f?.fid ?? ""),
                  arcTag: COPY.arcTag(arc?.fid ?? "", arc?.station.name ?? ""), street: COPY.street, lift: COPY.lift,
                }} />
              </Canvas>
            )}
          </div>
          <div className="ci-shade" aria-hidden="true" />
          <nav className="ci-rail" aria-label={COPY.railLabel}>
            {COPY.rail.map((name, i) => (
              <button key={name} aria-current={active === i ? "step" : undefined} aria-label={COPY.goTo(name)} onClick={() => go(i)}>
                <span className="ci-rail-dot" aria-hidden="true" />
                <span className="ci-rail-name" aria-hidden="true">{name}</span>
              </button>
            ))}
          </nav>
        </div>

        <div className="ci-steps">
          <article className="ci-step ci-hero" ref={(el) => { steps.current[0] = el; }}>
            <motion.div data-anchor className="ci-hero-inner" {...reveal}>
              <p className="ci-eyebrow">{COPY.eyebrow}</p>
              <h1 className="ci-title">{COPY.title}</h1>
              {claims && <>
                <p className="ci-count">
                  <span aria-hidden="true">{COPY.countOf(count, claims.platforms_step_free)}</span>
                  <span className="ci-sr">{COPY.countOf(claims.platforms_single_lift, claims.platforms_step_free)}</span>
                </p>
                <p className="ci-lede">{COPY.countText}</p>
              </>}
              <button className="ci-scroll" onClick={() => go(1)}>
                <span>{COPY.scroll}</span><span className="ci-chev" aria-hidden="true" />
              </button>
            </motion.div>
          </article>

          <article className="ci-step ci-right" ref={(el) => { steps.current[1] = el; }}>
            <motion.div data-anchor className="ci-panel" {...reveal}>
              <p className="ci-eyebrow"><span className="ci-index" aria-hidden="true">{String(2).padStart(2, "0")}</span>
                {COPY.s1eyebrow(f?.station.name ?? "")}</p>
              <h2>{COPY.s1title}</h2>
              {f && <>
                <p className="ci-stat"><span className="ci-stat-n ci-gold">{f.platforms}</span>
                  <span className="ci-stat-l">{COPY.s1stat(f.fid)}</span></p>
                <p>{COPY.s1body(f.station.name, f.closed.join(", "), f.fid, f.platforms)}</p>
                <p className="ci-legend" aria-hidden="true"><span className="ci-key ci-key-k0" />{COPY.closedTag(f.closed.join(", "))}
                  <span className="ci-key ci-key-gold" />{COPY.lastTag(f.fid)}</p>
              </>}
            </motion.div>
          </article>

          <article className="ci-step" ref={(el) => { steps.current[2] = el; }}>
            <motion.div data-anchor className="ci-panel" {...reveal}>
              <p className="ci-eyebrow"><span className="ci-index" aria-hidden="true">{String(3).padStart(2, "0")}</span>{COPY.s2eyebrow}</p>
              <h2>{COPY.s2title}</h2>
              {claims && <>
                <p className="ci-stat"><span className="ci-stat-n ci-amber">{claims.naive_two_lifts_but_k1}</span>
                  <span className="ci-stat-l">{COPY.s2stat}</span></p>
                <p>{COPY.s2body(claims.platforms_single_lift, singleStations, claims.naive_two_lifts_but_k1)}</p>
              </>}
            </motion.div>
          </article>

          <article className="ci-step ci-right" ref={(el) => { steps.current[3] = el; }}>
            <motion.div data-anchor className="ci-panel" {...reveal}>
              <p className="ci-eyebrow"><span className="ci-index" aria-hidden="true">{String(4).padStart(2, "0")}</span>{COPY.s3eyebrow}</p>
              <h2>{COPY.s3title}</h2>
              {claims && arc && <>
                <p className="ci-stat"><span className="ci-stat-n ci-red">{arc.od}</span>
                  <span className="ci-stat-l">{COPY.s3stat(arc.fid)}</span></p>
                <p>{COPY.s3body(claims.net_spof_lifts, arc.fid, arc.station.name, arc.od, claims.net_od_pairs)}</p>
              </>}
              <a className="ci-btn ci-ghost" href="#/network">{COPY.network} <span aria-hidden="true">→</span></a>
            </motion.div>
          </article>

          <article className="ci-step ci-dive" ref={(el) => { steps.current[4] = el; }}>
            <motion.div data-anchor className="ci-panel ci-panel-wide" {...reveal}>
              <p className="ci-eyebrow"><span className="ci-index" aria-hidden="true">{String(5).padStart(2, "0")}</span>{COPY.s4eyebrow}</p>
              <h2>{COPY.s4title}</h2>
              {claims && <>
                <p className="ci-stat"><span className="ci-stat-n ci-blue">{COPY.countOf(claims.falkordb_certified, claims.maxflow_calls)}</span>
                  <span className="ci-stat-l">{COPY.s4stat}</span></p>
                <p>{COPY.s4body(claims.falkordb_certified, claims.maxflow_calls, f?.station.name ?? "")}</p>
              </>}
              {f && (
                <div className="ci-ctas">
                  <a className="ci-btn ci-primary" href={`#/station/${f.station.id}?dir=exit`}>{COPY.open(f.station.name)} <span aria-hidden="true">→</span></a>
                  <a className="ci-btn ci-ghost" href="#/network">{COPY.network}</a>
                </div>
              )}
            </motion.div>
          </article>
        </div>
        <span id="ci-end" tabIndex={-1} />
      </section>
    </MotionConfig>
  );
}
