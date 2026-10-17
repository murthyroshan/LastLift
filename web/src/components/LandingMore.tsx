import { useEffect, useRef } from "react";
import { lessMotion, scrollVelocity } from "../lib/motion";
import { href } from "../router";
import { S } from "../strings.en";
import { Scramble } from "./Scramble";

/** A giant outlined line of type that drifts sideways and speeds up (and reverses) with the scroll. */
function Marquee({ text }: { text: string }) {
  const track = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (lessMotion()) return;
    let x = 0, raf = 0, dir = -1;
    const loop = () => {
      const v = scrollVelocity();
      if (Math.abs(v) > 0.2) dir = v > 0 ? -1 : 1;
      x += dir * (0.6 + Math.min(14, Math.abs(v) * 0.9));
      const w = (track.current?.scrollWidth ?? 2) / 2;
      if (x < -w) x += w; if (x > 0) x -= w;
      if (track.current) track.current.style.transform = `translate3d(${x}px, 0, 0)`;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);
  const run = Array.from({ length: 4 }, () => text).join("   ·   ");
  return (
    <div className="lm-marquee" aria-hidden="true">
      <div className="lm-track" ref={track}><span>{run}   ·   </span><span>{run}   ·   </span></div>
    </div>
  );
}

/** Reveal children as they scroll into view (once). */
function useReveal() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    if (lessMotion()) { el.classList.add("in"); return; }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { el.classList.add("in"); io.disconnect(); } }, { threshold: 0.2 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return ref;
}

/** The landing after the product: how it works in three steps, where to go next, and a closing wordmark. */
export function LandingMore() {
  const how = useReveal(), more = useReveal();
  return (
    <>
      <Marquee text={S.more.marquee} />

      <section className="lm-how" aria-labelledby="lm-how-h">
        <h2 id="lm-how-h" className="lm-h"><Scramble text={S.more.howTitle} /></h2>
        <div className="lm-steps" ref={how}>
          {S.more.how.map((s) => (
            <article key={s.t} className="lm-step">
              <h3><Scramble text={s.t} ms={700} /></h3>
              <p>{s.d}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="lm-explore" aria-labelledby="lm-ex-h">
        <h2 id="lm-ex-h" className="lm-h"><Scramble text={S.more.exploreTitle} /></h2>
        <div className="lm-cards" ref={more}>
          {S.more.explore.map((c) => (
            <a key={c.path} className="lm-card" href={href(c.path)}>
              <span className="lm-card-t">{c.t}</span>
              <span className="lm-card-d">{c.d}</span>
              <span className="lm-card-go" aria-hidden="true">→</span>
            </a>
          ))}
        </div>
      </section>

      <footer className="lm-foot">
        <p className="lm-foot-word" aria-hidden="true">{S.appName}</p>
        <p className="lm-foot-line"><Scramble text={S.more.footer} ms={1200} /></p>
      </footer>
    </>
  );
}
