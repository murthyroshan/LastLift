/** UI11 display and reading settings: theme (system, light, dark, high contrast), text size, motion and simple
 *  language. Stored per browser (any storage failure means defaults). Components that read the system media queries
 *  through window.matchMedia see these choices too, so canvases and maps follow the same settings. */
export type Display = { theme: "system" | "light" | "dark" | "contrast"; size: number; motion: "system" | "reduce"; simple: boolean;
  readable?: boolean };

// v2: earlier builds saved their defaults on every load (theme "system"), which would now override the light default
const KEY = "lastlift.display.v2";
export const DEFAULTS: Display = { theme: "light", size: 100, motion: "system", simple: false };

export function loadDisplay(): Display {
  try {
    window.localStorage.removeItem("lastlift.display");
    return { ...DEFAULTS, ...JSON.parse(window.localStorage.getItem(KEY) ?? "{}") };
  } catch { return DEFAULTS; }
}

let current: Display = DEFAULTS;

/** Apply settings; `save` only when the reader chose them in the panel, so defaults never get frozen in storage. */
export function applyDisplay(d: Display, save = false) {
  current = d;
  const html = document.documentElement;
  if (d.theme === "system") delete html.dataset.theme; else html.dataset.theme = d.theme === "contrast" ? "dark" : d.theme;
  if (d.theme === "contrast") html.dataset.contrast = "more"; else delete html.dataset.contrast;
  if (d.motion === "reduce") html.dataset.motion = "reduce"; else delete html.dataset.motion;
  if (d.simple) html.dataset.simple = "on"; else delete html.dataset.simple;
  if (d.readable) html.dataset.readable = "on"; else delete html.dataset.readable;
  html.style.fontSize = d.size === 100 ? "" : `${d.size}%`;
  if (save) try { window.localStorage.setItem(KEY, JSON.stringify(d)); } catch { /* storage unavailable */ }
}

export const simpleOn = () => current.simple;

/** Wrap matchMedia once so the chosen theme and motion win over the system's. */
export function installMediaOverrides() {
  const native = window.matchMedia.bind(window);
  const fake = (media: string, matches: boolean): MediaQueryList => ({
    matches, media, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
    dispatchEvent: () => false,
  }) as MediaQueryList;
  window.matchMedia = (q: string) => {
    if (q.includes("prefers-reduced-motion: reduce") && current.motion === "reduce") return fake(q, true);
    if (q.includes("prefers-color-scheme: dark") && current.theme !== "system") return fake(q, current.theme !== "light");
    if (q.includes("prefers-contrast: more") && current.theme === "contrast") return fake(q, true);
    return native(q);
  };
}
