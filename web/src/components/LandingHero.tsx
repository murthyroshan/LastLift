import { useEffect, useRef, useState } from "react";
import { href } from "../router";
import { S } from "../strings.en";
import type { Scope } from "../api";
import { LiftPanel } from "./LiftPanel";

const BASE = import.meta.env.BASE_URL;
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** A soft two-note lift chime, only ever after a press (never on its own). */
function chime() {
  try {
    const ctx = new AudioContext(), now = ctx.currentTime;
    [[784, 0], [659, 0.32]].forEach(([f, t]) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "sine"; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, now + t); g.gain.exponentialRampToValueAtTime(0.18, now + t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, now + t + 1.1);
      o.connect(g).connect(ctx.destination); o.start(now + t); o.stop(now + t + 1.2);
    });
  } catch { /* no audio: nothing is lost */ }
}

/** Counts up to `to` once `on` is true (instantly under reduced motion). */
function useCount(to: number | undefined, on: boolean, ms = 1300) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (!on || to == null) return;
    if (reduced()) { setV(to); return; }
    const t0 = performance.now(); let raf = 0;
    const step = (now: number) => { const k = Math.min(1, (now - t0) / ms); setV(Math.round(to * (1 - Math.pow(1 - k, 4)))); if (k < 1) raf = requestAnimationFrame(step); };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [to, on, ms]);
  return v;
}

function Stat({ n, of, label, k }: { n: number; of?: number; label: string; k: "one" | "lost" | "ok" }) {
  const box = useRef<HTMLDivElement>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const io = new IntersectionObserver(([e]) => e.isIntersecting && setSeen(true), { threshold: 0.4 });
    if (box.current) io.observe(box.current);
    return () => io.disconnect();
  }, []);
  const v = useCount(n, seen);
  return (
    <div className="lh-stat" data-k={k} ref={box}>
      <span className="lh-stat-n" aria-hidden="true">{v}{of != null && <em>/{of}</em>}</span>
      <span className="visually-hidden">{of != null ? `${n} / ${of}` : n}</span>
      <span className="lh-stat-l">{label}</span>
    </div>
  );
}

/** The landing: lift doors that open onto the headline, a tilting model, a strip of stations, the four numbers. */
export function LandingHero({ claims, stations, film = false, scope = "demo" }: { claims: Record<string, any> | null;
  stations: { id: string; name: string; single: number; lost: number }[]; film?: boolean; scope?: Scope }) {
  const [open, setOpen] = useState(() => film || reduced() || sessionStorage.getItem("lastlift.doors") === "open");
  const [paused, setPaused] = useState(false);
  const floor = useCount(claims?.platforms_single_lift, true, 1500);

  useEffect(() => {                                   // the doors open by themselves after the count, once a visit
    if (open || !claims) return;
    const t = window.setTimeout(() => setOpen(true), 1900);
    return () => clearTimeout(t);
  }, [open, claims]);
  useEffect(() => { if (open) try { sessionStorage.setItem("lastlift.doors", "open"); } catch { /* ignore */ } }, [open]);

  const strip = stations.filter((s) => s.single > 0 || s.lost > 0).sort((a, b) => b.lost - a.lost || b.single - a.single);

  return (
    <>
      <section id="lh-product" className={`lh ${open ? "lh-open" : ""} ${film ? "lh-after-film" : ""}`} aria-label={S.panel.title}>
        {!film && <div className="lh-doors" aria-hidden="true">
          <div className="lh-door lh-door-l" />
          <div className="lh-door lh-door-r" />
          <div className="lh-indicator"><span className="lh-arrow">▲</span><span className="lh-floor">{floor}</span></div>
          <button className="lh-call" tabIndex={-1} onClick={() => { chime(); setOpen(true); }}>
            <span className="lh-call-ring" /><span className="lh-call-label">{S.landing.call}</span>
          </button>
        </div>}

        <div className="lh-product"><LiftPanel scope={scope} /></div>
        <span className="lh-ghost" aria-hidden="true">{claims?.platforms_single_lift ?? ""}</span>
      </section>

      {!film && <section className="lh-copy-band" aria-labelledby="hero-h">
        <div className="lh-copy">
          <p className="lh-eyebrow">{S.home.eyebrow}</p>
          <h1 id="hero-h" className="lh-title">{S.tagline}</h1>
          {claims && <p className="lh-count ci-count">
            <span className="lh-big">{claims.platforms_single_lift}</span>
            <span className="lh-of"> {S.landing.of} {claims.platforms_step_free}</span>
          </p>}
          <p className="lh-line">{S.home.countText}</p>
          <div className="lh-ctas">
            <a className="lh-btn lh-btn-ink" href={`${BASE}concepts/sequence.html`}>{S.hero.story}<span aria-hidden="true">→</span></a>
            <a className="lh-btn" href={`${BASE}concepts/world.html`}>{S.hero.walk}</a>
            <a className="lh-btn lh-btn-ghost" href={href("/console")}>{S.hero.console}</a>
          </div>
        </div>
      </section>}

      {strip.length > 0 && (
        <section className={`lh-strip ${paused ? "paused" : ""}`} aria-label={S.landing.stripLabel}>
          <button className="lh-pause" aria-pressed={paused} onClick={() => setPaused(!paused)}>{paused ? S.landing.play : S.landing.pause}</button>
          <div className="lh-track" aria-hidden="true">
            {[...strip, ...strip].map((s, i) => (
              <a key={`${s.id}-${i}`} href={href(`/station/${s.id}`)} tabIndex={-1}>
                <span className="lh-st">{s.name}</span>
                {s.lost > 0 ? <span className="lh-k" data-k="lost">✕ {s.lost}</span> : <span className="lh-k" data-k="one">◆ {s.single}</span>}
              </a>
            ))}
          </div>
          <p className="visually-hidden">{S.landing.stripText(strip.length)}</p>
        </section>
      )}

      {claims && (
        <section className="lh-stats" aria-label={S.landing.statsLabel}>
          <Stat n={claims.platforms_single_lift} of={claims.platforms_step_free} label={S.landing.s1} k="one" />
          <Stat n={claims.spof_lifts} label={S.landing.s2} k="one" />
          <Stat n={claims.net_spof_lifts} label={S.landing.s3} k="lost" />
          <Stat n={claims.falkordb_certified} of={claims.maxflow_calls} label={S.landing.s4} k="ok" />
        </section>
      )}
    </>
  );
}
