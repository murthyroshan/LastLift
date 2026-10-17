// Render the landing film frame by frame on the real GPU: node scripts/film.mjs <outdir> <frames> [w] [h] [only]
//   only: a comma list of frame numbers to render (for test frames), e.g. "0,120,230"
// Runs one headed Chromium (the laptop's GPU, not software WebGL), one frame at a time, nothing in parallel.
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

const [outDir, nArg = "240", wArg = "1600", hArg = "900", only] = process.argv.slice(2);
const n = Number(nArg), w = Number(wArg), h = Number(hArg);
const base = process.env.SHOTS_BASE || "http://localhost:5173/";
mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch({ headless: false, args: ["--ignore-gpu-blocklist", "--enable-gpu-rasterization", `--window-size=${w},${h + 120}`] });
const page = await browser.newPage({ viewport: { width: w, height: h } });
await page.goto(`${base}#/lab/film?w=${w}&h=${h}`, { waitUntil: "networkidle" });
await page.waitForFunction(() => (window).__filmReady === true, null, { timeout: 120000 });
const renderer = await page.evaluate(() => {
  const gl = document.createElement("canvas").getContext("webgl2");
  const i = gl && gl.getExtension("WEBGL_debug_renderer_info");
  return i ? gl.getParameter(i.UNMASKED_RENDERER_WEBGL) : "unknown";
});
console.log("renderer:", renderer);
await page.waitForTimeout(1500);                 // let textures and the environment settle
const list = only ? only.split(",").map(Number) : Array.from({ length: n }, (_, i) => i);
const t0 = Date.now();
for (const i of list) {
  const url = await page.evaluate(([i, n]) => (window).__film(i, n), [i, n]);
  writeFileSync(`${outDir}/f${String(i).padStart(3, "0")}.webp`, Buffer.from(url.split(",")[1], "base64"));
  if (i % 20 === 0 || only) console.log(`frame ${i}/${n - 1}  ${((Date.now() - t0) / 1000).toFixed(1)} s`);
}
await browser.close();
