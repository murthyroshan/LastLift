import { useEffect, useState } from "react";
import { flushSync } from "react-dom";

export type Route = { path: string; parts: string[]; query: URLSearchParams };

function parse(): Route {
  const raw = window.location.hash.replace(/^#/, "") || "/";
  const [path, q = ""] = raw.split("?");
  return { path, parts: path.split("/").filter(Boolean), query: new URLSearchParams(q) };
}

/** Hash routing: works on any static host and keeps deep links shareable (#/station/place-alfcl?dir=exit). */
/** Between top-level sections an ink panel sweeps up carrying the destination's name, the page swaps behind it,
 *  and the panel lifts away. Skipped under reduced motion. */
async function wipe(label: string, swap: () => Promise<void>) {
  const el = document.createElement("div");
  el.className = "ll-wipe"; el.setAttribute("aria-hidden", "true");
  const word = document.createElement("span"); word.textContent = label; el.appendChild(word);
  document.body.appendChild(el);
  const ease = "cubic-bezier(.77, 0, .18, 1)";
  await el.animate([{ clipPath: "inset(100% 0 0 0)" }, { clipPath: "inset(0 0 0 0)" }], { duration: 420, easing: ease, fill: "forwards" }).finished;
  await swap();
  window.scrollTo(0, 0);
  await el.animate([{ clipPath: "inset(0 0 0 0)" }, { clipPath: "inset(0 0 100% 0)" }], { duration: 560, delay: 140, easing: ease, fill: "forwards" }).finished;
  el.remove();
}

const reducedMotion = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.dataset.motion === "reduce";

export function useRoute(): Route {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    let section = parse().parts[0] ?? "";
    const on = () => {
      const next = parse().parts[0] ?? "";
      const changed = next !== section;
      section = next;
      const swap = () => flushSync(() => setRoute(parse()));
      // the new page's data loads asynchronously: let the transition wait (briefly) for its heading to render
      const swapAndSettle = async () => {
        swap();
        const t0 = performance.now();
        while (!document.querySelector("#main h1") && performance.now() - t0 < 800) await new Promise((r) => setTimeout(r, 30));
      };
      if (changed && !reducedMotion()) {
        const link = document.querySelector<HTMLAnchorElement>(`nav.site a[href="#/${next}"]`);
        wipe((link?.textContent || next || "LastLift").trim(), swapAndSettle)
          .finally(() => { document.querySelector(".vt-dot")?.remove(); document.getElementById("main")?.focus(); });
        return;
      }
      const doc = document as Document & { startViewTransition?: (cb: () => void | Promise<void>) => { finished: Promise<void> } };
      // UI10: a view transition between pages (and the map-dot-to-x-ray morph); skipped under reduced motion and
      // where the browser has no View Transitions API, which then simply swaps the page.
      if (doc.startViewTransition && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        doc.startViewTransition(swapAndSettle).finished.finally(() => document.querySelector(".vt-dot")?.remove()).catch(() => {});
      } else {
        swap();
        document.querySelector(".vt-dot")?.remove();
      }
      document.getElementById("main")?.focus();       // move focus to the new page for keyboard users
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export const href = (path: string, query?: Record<string, string>) =>
  `#${path}${query && Object.keys(query).length ? `?${new URLSearchParams(query)}` : ""}`;
