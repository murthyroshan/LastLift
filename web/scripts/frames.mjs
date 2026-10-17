// Turn the landing film's clips into a scroll-scrub frame sequence: node scripts/frames.mjs <fps> <clip.mp4> [clip.mp4 ...]
// Writes public/film/{lg,sm}/fNNN.webp and public/film/manifest.json. The clips play back to back as one film; a clip
// that continues the one before it (an extension) starts on that clip's last frame, so its first sample is dropped.
// Decodes in one headless Chrome (H.264 needs Chrome, not the bundled Chromium), one frame at a time.
import { chromium } from "@playwright/test";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";

const [fpsArg, ...clips] = process.argv.slice(2);
const fps = Number(fpsArg);
if (!fps || !clips.length) { console.error("usage: node scripts/frames.mjs <fps> <clip.mp4> [clip.mp4 ...]"); process.exit(1); }
const SIZES = { lg: 1280, sm: 820 };
const INSET = Number(process.env.FRAMES_INSET ?? 0.03);   // trim each edge a little, which also drops the generator's corner mark
// FRAMES_PATCH="x,y,w,h,dx,dy" (fractions of the frame): cover a generator's watermark with the patch of frame offset by dx,dy
const PATCH = (process.env.FRAMES_PATCH || "").split(",").filter(Boolean).map(Number);
const GRADE = process.env.FRAMES_GRADE || "none";
// FRAMES_CROP="left,top,right,bottom" (fractions): an uneven trim, e.g. to cut a watermark off one edge; overrides INSET
const CROP = (process.env.FRAMES_CROP || "").split(",").filter(Boolean).map(Number);             // a CSS filter applied to every frame, e.g. "brightness(1.15)"
const QUALITY = { lg: 0.74, sm: 0.7 };
const out = "public/film";
rmSync(out, { recursive: true, force: true });
for (const s of Object.keys(SIZES)) mkdirSync(`${out}/${s}`, { recursive: true });

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage();
await page.setContent("<video muted playsinline preload=auto></video><canvas></canvas>");
let n = 0, w = 0, h = 0;
for (const [k, clip] of clips.entries()) {
  const b64 = readFileSync(clip).toString("base64");
  const dur = await page.evaluate(async (b64) => {
    const v = document.querySelector("video");
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    v.src = URL.createObjectURL(new Blob([bytes], { type: "video/mp4" }));
    await new Promise((res, rej) => { v.onloadeddata = res; v.onerror = () => rej(new Error("cannot decode")); });
    return v.duration;
  }, b64);
  const count = Math.floor(dur * fps);
  console.log(`${clip}: ${dur.toFixed(2)} s -> ${count} frames`);
  for (let i = k === 0 ? 0 : 1; i < count; i++) {
    const t = Math.min(dur - 0.001, (i + 0.5) / fps);
    const shots = await page.evaluate(async ([t, SIZES, QUALITY, INSET, PATCH, GRADE, CROP]) => {
      const v = document.querySelector("video"), c = document.querySelector("canvas");
      await new Promise((res) => { v.onseeked = res; v.currentTime = t; });
      // the source frame, with any watermark patched over, before trimming and scaling
      const f = document.createElement("canvas"); f.width = v.videoWidth; f.height = v.videoHeight;
      const fg = f.getContext("2d"); fg.drawImage(v, 0, 0);
      if (PATCH.length === 6) {
        const [x, y, w, h, dx, dy] = PATCH.map((n, i) => n * (i % 2 ? f.height : f.width));
        fg.drawImage(f, x + dx, y + dy, w, h, x, y, w, h);
      }
      const r = {};
      for (const [s, W] of Object.entries(SIZES)) {
        const H = Math.round((W * v.videoHeight) / v.videoWidth);
        c.width = W; c.height = H;
        const g = c.getContext("2d"); g.imageSmoothingQuality = "high"; g.filter = GRADE;
        const [l, tp, rt, bt] = CROP.length === 4 ? CROP : [INSET, INSET, INSET, INSET];
        g.drawImage(f, f.width * l, f.height * tp, f.width * (1 - l - rt), f.height * (1 - tp - bt), 0, 0, W, H);
        r[s] = { url: c.toDataURL("image/webp", QUALITY[s]), W, H };
      }
      return r;
    }, [t, SIZES, QUALITY, INSET, PATCH, GRADE, CROP]);
    for (const [s, x] of Object.entries(shots)) {
      writeFileSync(`${out}/${s}/f${String(n).padStart(3, "0")}.webp`, Buffer.from(x.url.split(",")[1], "base64"));
      if (s === "lg") { w = x.W; h = x.H; }
    }
    n++;
  }
}
await browser.close();
writeFileSync(`${out}/manifest.json`, JSON.stringify({ n, fps, w, h, sizes: SIZES, v: Date.now().toString(36) }, null, 2));
console.log(`${n} frames written to ${out}`);
