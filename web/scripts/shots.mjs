// Screenshots of the live dev server for visual review: node scripts/shots.mjs <outdir> <route> [<route> ...]
// Each route is "name=#/path" with optional "@WxH" and "!scroll=N" (pixels) suffixes.
import { chromium } from "@playwright/test";

const [outDir, ...routes] = process.argv.slice(2);
const base = process.env.SHOTS_BASE || "http://localhost:5173/";
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
for (const spec of routes) {
  const [nameAndPath, ...mods] = spec.split("!");
  const cut = nameAndPath.indexOf("=");
  const name = nameAndPath.slice(0, cut), rest = nameAndPath.slice(cut + 1);
  const [path, size = "1440x900"] = rest.split("@");
  const [w, h] = size.split("x").map(Number);
  const scheme = name.endsWith("-light") ? "light" : "dark";
  const page = await browser.newPage({ viewport: { width: w, height: h }, colorScheme: scheme });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
  await page.goto(`${base}${path}`, { waitUntil: "networkidle", timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(Number(process.env.WAIT ?? 5000));
  for (const m of mods) {
    const k = m.slice(0, m.indexOf("=")), v = m.slice(m.indexOf("=") + 1);
    if (k === "scroll") { await page.mouse.wheel(0, Number(v)); await page.waitForTimeout(3500); }
    if (k === "click") { await page.click(v).catch((e) => errors.push(`click ${v}: ${e}`.slice(0, 200))); await page.waitForTimeout(3500); }
  }
  const info = await page.evaluate(() => [location.href, document.querySelector("main")?.firstElementChild?.className ?? "", document.title].join(" ; "));
  await page.screenshot({ path: `${outDir}/${name}.png`, timeout: 180000 });
  console.log(name, info);
  console.log(name, errors.length ? `errors: ${errors.join(" / ")}` : "ok");
  await page.close();
}
await browser.close();
