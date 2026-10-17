import { useEffect, useRef } from "react";
import { lessMotion } from "../lib/motion";

const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ#%&@*+=/<>";

/** Text that decodes from random characters, left to right, the first time it scrolls into view.
 *  Assistive technology reads the real text; the animated copy is hidden from it. */
export function Scramble({ text, ms = 900 }: { text: string; ms?: number }) {
  const out = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const el = out.current; if (!el) return;
    if (lessMotion()) { el.textContent = text; return; }
    let raf = 0;
    const run = () => {
      const t0 = performance.now();
      const step = (now: number) => {
        const k = Math.min(1, (now - t0) / ms);
        el.textContent = [...text].map((c, i) => {
          if (c === " " || k >= 1 || k > 0.25 + (0.75 * i) / text.length) return c;
          return GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
        }).join("");
        if (k < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    };
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { io.disconnect(); run(); } }, { threshold: 0.4 });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [text, ms]);
  return (
    <>
      <span className="visually-hidden">{text}</span>
      <span ref={out} aria-hidden="true">{text}</span>
    </>
  );
}
