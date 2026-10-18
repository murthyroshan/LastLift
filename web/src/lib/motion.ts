import Lenis from "lenis";

/** Whether the visitor (or the Display panel) asked for less motion. */
export const lessMotion = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.dataset.motion === "reduce";

let lenis: Lenis | null = null;

/** Smooth, inertial scrolling for the landing page. Returns a stop function; does nothing under reduced motion. */
export function startSmoothScroll(): () => void {
  if (lessMotion() || lenis) return () => {};
  lenis = new Lenis({
    lerp: 0.09, wheelMultiplier: 0.9, allowNestedScroll: true,
    // maps zoom, tables and panels scroll themselves, dialogs keep their own scroll
    prevent: (node: HTMLElement) => !!node.closest?.(".maplibregl-map, .livemap, canvas, .table-wrap, .console, .chat, [role=dialog], textarea, select, [data-lenis-prevent]"),
  });
  let raf = 0;
  const loop = (t: number) => { lenis?.raf(t); raf = requestAnimationFrame(loop); };
  raf = requestAnimationFrame(loop);
  return () => { cancelAnimationFrame(raf); lenis?.destroy(); lenis = null; };
}

/** Scroll to a page offset, through the smooth scroller when it is running. */
export function scrollToY(y: number) {
  if (lenis) lenis.scrollTo(y, { duration: 1.4 });
  else window.scrollTo({ top: y, behavior: lessMotion() ? "auto" : "smooth" });
}

/** The current scroll velocity in pixels per frame (0 without the smooth scroller). */
export const scrollVelocity = () => lenis?.velocity ?? 0;

/** A small ring that trails the pointer and swells over anything clickable (pointer devices only). */
export function startCursor(): () => void {
  if (lessMotion() || !window.matchMedia("(pointer: fine)").matches) return () => {};
  const dot = document.createElement("div");
  dot.className = "ll-cursor"; dot.setAttribute("aria-hidden", "true");
  document.body.appendChild(dot);
  let x = -100, y = -100, tx = x, ty = y, raf = 0;
  const move = (e: PointerEvent) => {
    tx = e.clientX; ty = e.clientY;
    dot.classList.toggle("hot", !!(e.target as Element)?.closest?.("a, button, [role=button], input, label"));
  };
  const loop = () => {
    x += (tx - x) * 0.22; y += (ty - y) * 0.22;
    dot.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    raf = requestAnimationFrame(loop);
  };
  window.addEventListener("pointermove", move);
  raf = requestAnimationFrame(loop);
  return () => { cancelAnimationFrame(raf); window.removeEventListener("pointermove", move); dot.remove(); };
}
