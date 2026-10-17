// Record the muted-safe 15 s opener (MS6): eyes-free mode answering from the recorded Revere Beach run, captions from
// docs/film/opener.srt burned into the page. Needs the built site served (npx vite preview --port 4173).
//   node web/scripts/record_opener.mjs        -> data/raw/film/<id>.webm  (convert: ffmpeg -i in.webm out.mp4)
import { chromium } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";

const cues = readFileSync(new URL("../../docs/film/opener.srt", import.meta.url), "utf-8").trim().split(/\r?\n\r?\n/)
  .map((b) => { const [, t, ...txt] = b.split(/\r?\n/); const [a, z] = t.split(" --> ").map((s) => {
    const [h, m, rest] = s.split(":"); const [sec, ms] = rest.split(","); return (+h * 3600 + +m * 60 + +sec) * 1000 + +ms; });
    return { a, z, text: txt.join(" ") }; });
mkdirSync("data/raw/film", { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 },
  recordVideo: { dir: "data/raw/film", size: { width: 1280, height: 720 } }, reducedMotion: "no-preference" });
const page = await ctx.newPage();
await page.addInitScript((cuesIn) => {
  window.addEventListener("DOMContentLoaded", () => {
    const cap = document.createElement("div");
    cap.style.cssText = "position:fixed;left:5%;right:5%;bottom:48px;text-align:center;font:600 30px system-ui;" +
      "color:#fff;background:rgba(0,0,0,.72);padding:12px 18px;border-radius:10px;z-index:9999";
    const black = document.createElement("div");
    black.style.cssText = "position:fixed;inset:0;background:#000;z-index:9998;transition:opacity .8s";
    document.body.append(black, cap);
    const t0 = performance.now();
    const tick = () => {
      const t = performance.now() - t0;
      const c = cuesIn.find((x) => t >= x.a && t < x.z);
      cap.textContent = c ? c.text : ""; cap.style.display = c ? "block" : "none";
      black.style.opacity = t < 7000 ? "1" : "0";
      if (t < 15500) requestAnimationFrame(tick);
    };
    tick();
  });
}, cues);
await page.goto("http://localhost:4173/?eyesfree=1&present=1#/station/place-rbmnl?dir=board");
const box = page.getByLabel("Or type a question or a command");
await page.waitForTimeout(3000);
await box.fill("Can I get step-free onto the Wonderland-bound platform at Revere Beach right now?");
await page.waitForTimeout(3500);
await box.press("Enter");
await page.waitForTimeout(8500);
await ctx.close();
await browser.close();
console.log("recorded into data/raw/film/");
