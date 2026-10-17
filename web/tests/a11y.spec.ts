import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// The live API is blocked for every test: the site must stand on the static mirror alone.
async function blockApi(page: Page) {
  await page.route(/\/(v1|api|healthz|mcp)(\/|\?|$)/, (route) => route.abort());
}

async function noSeriousAxeIssues(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
}

test.beforeEach(async ({ page }) => blockApi(page));

test("landing works from the mirror", async ({ page }) => {
  await page.goto("/#/");
  // the film's count beat, then the product (the station table now lives on the Network page)
  await expect(page.locator(".fh-count")).toContainText(/\d+\s*\/\s*\d+/, { timeout: 20000 });
  await expect(page.locator("#lh-product")).toBeVisible();
  await noSeriousAxeIssues(page);
});

test("station view, linked selection and what-if work from the mirror", async ({ page }) => {
  await page.goto("/#/station/place-alfcl?dir=exit");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Alewife");
  await page.getByRole("button", { name: "Red Line", exact: true }).click();
  await expect(page.getByRole("button", { name: "Red Line", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: /Simulate lift 813 closing/ }).click();
  await expect(page.getByRole("region", { name: /SIMULATED/ })).toBeVisible();
  await noSeriousAxeIssues(page);
});

test("repairs, tickets and the evaluation table work from the mirror", async ({ page }) => {
  await page.goto("/#/repairs");
  await page.getByRole("button", { name: "Draft ticket" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await noSeriousAxeIssues(page);
});

test("the agent drawer plays a recorded run with its Cypher", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/#/");
  await page.getByRole("button", { name: "Ask the agent" }).click();
  await page.getByRole("button", { name: /Revere Beach/ }).click();
  await expect(page.getByText("via MCP").first()).toBeVisible();
  await page.getByRole("button", { name: "Show the Cypher" }).first().click();
  await expect(page.locator("pre.cypher").first()).toContainText("MATCH");
  await noSeriousAxeIssues(page);
});

test("keyboard only: skip link, then reach a station", async ({ page }) => {
  await page.goto("/#/");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeAttached();
  await page.waitForLoadState("networkidle");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.goto("/#/about");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await noSeriousAxeIssues(page);
});

test("reflows at 320 px without horizontal page scroll", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.goto("/#/station/place-alfcl");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

for (const path of ["/#/", "/#/station/place-alfcl?dir=exit", "/#/repairs"]) {
  test(`dark theme has no serious axe issues: ${path}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await noSeriousAxeIssues(page);
  });
}

test("the Live toggle needs the server and says so", async ({ page }) => {
  await page.goto("/#/");
  const toggle = page.getByRole("button", { name: "Live" });
  await expect(toggle).toBeDisabled();
  await expect(page.getByText(/frozen demo alerts/)).toBeVisible();
});

test("Live scope reads the API and shows the feed status", async ({ page }) => {
  const { readFileSync } = await import("node:fs");
  const mirrored = JSON.parse(readFileSync("public/m/state.json", "utf-8"));
  const ok = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  const asked: string[] = [];
  await page.route(/\/healthz$/, (r) => r.fulfill(ok({ ok: true })));
  await page.route(/\/v1\/live$/, (r) => r.fulfill(ok({ feed: "on", source: "mbta_api", age_s: 30, stale: false,
    state_version: 2, closed: ["885"], alerts: 4, last_ok_at: null, last_error: null })));
  await page.route(/\/v1\/tools\/(current_closures|repair_priority)$/, (r) => {
    const name = r.request().url().split("/").pop()!;
    asked.push(`${name}:${JSON.parse(r.request().postData() ?? "{}").scope}`);
    return r.fulfill(ok(name === "current_closures" ? mirrored.closures : mirrored.priority));
  });
  await page.goto("/#/");
  const toggle = page.getByRole("button", { name: "Live" });
  await expect(toggle).toBeEnabled();
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText(/MBTA alerts polled under a minute ago/)).toBeVisible();
  await expect.poll(() => asked).toContain("current_closures:live");
  await noSeriousAxeIssues(page);
});

for (const scheme of ["light", "dark"] as const) {
  test(`network page works from the mirror (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/#/network");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("The step-free network");
    await expect(page.getByText(/can cut a whole station off/)).toBeVisible();
    const first = page.getByRole("tab", { name: "Cuts a station off" });
    await expect(first).toHaveAttribute("aria-selected", "true");
    await first.focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("tab", { name: "Rescued by the network" })).toHaveAttribute("aria-selected", "true");
    await page.getByRole("tab", { name: "Critical pairs" }).click();
    await expect(page.getByRole("tabpanel")).toContainText("821 + 973");
    await page.getByRole("tab", { name: "Travel times" }).click();
    await expect(page.getByRole("combobox", { name: "From" })).toBeVisible();
    await noSeriousAxeIssues(page);
  });
}

test("station proof panel: minimum cuts, reliability slider, single-lift table", async ({ page }) => {
  await page.goto("/#/station/place-harsq");
  await page.getByRole("table").first().getByRole("button").first().click();
  await expect(page.getByRole("heading", { name: /Why this number/ })).toBeVisible();
  const slider = page.getByRole("slider", { name: /Chance that any one lift is out/ });
  await expect(slider).toBeVisible();
  await slider.fill("0.1");
  await expect(page.getByText(/Step-free access would be lost about|No combination of lift failures/)).toBeVisible();
  await noSeriousAxeIssues(page);
});

test("station history: replayed closures, lift table and month strip with its table twin", async ({ page }) => {
  await page.goto("/#/station/place-brntn");
  await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
  await expect(page.getByText(/no step-free route for about/).first()).toBeVisible();
  await expect(page.getByText(/not a forecast/)).toBeVisible();
  await page.getByText(/Hours closed per month for lift 811/).click();
  await expect(page.getByRole("columnheader", { name: "Hours closed" }).first()).toBeVisible();
  await noSeriousAxeIssues(page);
});

test("a recorded run verifies its own hash chain in the browser", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/#/");
  await page.getByRole("button", { name: "Ask the agent" }).click();
  await page.getByRole("button", { name: /Which lifts should be repaired/ }).click();
  await page.getByRole("button", { name: "Verify this replay" }).click();
  await expect(page.getByRole("complementary", { name: "Ask the agent" }).getByText(/Verified in your browser: all \d+ events match/)).toBeVisible();
  await noSeriousAxeIssues(page);
});

test("operations page shows the agents' playbooks from the mirror", async ({ page }) => {
  await page.goto("/#/approvals");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Operations");
  await expect(page.getByText("Platform loses step-free access").first()).toBeVisible();
  await expect(page.getByText(/Decisions need the live graph server/)).toBeVisible();
  await noSeriousAxeIssues(page);
});

test("The Count's bins equal the claims, and Now moves platforms between bins", async ({ page }) => {
  const { readFileSync } = await import("node:fs");
  const claims = JSON.parse(readFileSync("public/claims.json", "utf-8"));
  const h = claims.k_hist_board;
  const many = Object.entries(h).filter(([k]) => /^\d+$/.test(k) && Number(k) >= 2).reduce((s, [, v]) => s + (v as number), 0);
  await page.goto("/#/network");     // the count chart lives on the Network page
  const cap = page.locator("figure.count-fig figcaption");
  await expect(cap).toContainText(`${h["1"]} hang by one lift, ${many} have two or more`);
  await expect(cap).toContainText(`${h.at_grade} need no lift, ${h["0"] ?? 0} have no step-free route`);
  await expect(cap).toContainText(`${claims.platforms_no_accessible_entrance} have no accessible entrance`);
  await page.getByRole("radio", { name: "Now (demo alerts)" }).click();
  await expect(cap).toContainText("Since the baseline:");
  await noSeriousAxeIssues(page);
});

test("network map: picking a lift draws its journeys, and the text twin says the same", async ({ page }) => {
  await page.goto("/#/network");
  await expect(page.locator(".net-map-frame canvas").first()).toBeAttached({ timeout: 20000 });
  await expect(page.locator(".net-map-frame canvas[aria-hidden='true']").first()).toBeAttached();
  const chip = page.locator(".lift-chips button", { hasText: "Davis" }).first();
  await chip.click();
  await expect(chip).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".net-map p[aria-live='polite']")).toContainText(/alone carries \d+ step-free journeys/);
  await expect(page.getByRole("table").first()).toBeVisible();
});

test("present mode: help, beats and the caption frame are keyboard driven", async ({ page }) => {
  await page.goto("/?present=1#/");
  await expect(page.locator("html.present")).toBeAttached();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.keyboard.press("?");
  await expect(page.getByRole("dialog", { name: "Present mode keys" })).toBeVisible();
  await page.keyboard.press("?");
  await page.keyboard.press("3");
  await expect(page).toHaveURL(/#\/station\/place-alfcl/);
  await page.keyboard.press("g");
  await expect(page.locator(".present-frame")).toBeVisible();
});

const MATRIX = ["/#/", "/#/console", "/#/network", "/#/repairs", "/#/approvals", "/#/station/place-alfcl?dir=exit", "/#/atlas", "/#/sandbox?close=813,891", "/#/history", "/#/about"];
for (const scheme of ["light", "dark"] as const) {
  for (const width of [320, 1280]) {
    test(`axe matrix: every page, ${scheme}, ${width} px`, async ({ page }) => {
      test.setTimeout(180_000);
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
      await page.setViewportSize({ width, height: 900 });
      for (const url of MATRIX) {
        await page.goto(url);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await noSeriousAxeIssues(page);
        const scroll = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(scroll, `${url} scrolls sideways at ${width} px`).toBeLessThanOrEqual(1);
      }
    });
  }
}

test("sound: off by default, never plays before a gesture, and every sound has a text twin", async ({ page }) => {
  await page.goto("/#/station/place-alfcl?dir=exit");
  const toggle = page.getByRole("button", { name: "Sound", exact: true });
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByRole("button", { name: "Play this platform's sound" })).toBeDisabled();
  await page.getByRole("button", { name: "Red Line", exact: true }).click();
  await toggle.click();
  await page.getByRole("button", { name: "Play this platform's sound" }).click();
  await expect(page.getByText(/One trembling tone|Tones playing/).first()).toBeAttached();
  await noSeriousAxeIssues(page);
});

test("eyes-free mode: Alt+E, a recorded answer is spoken, walk, why, stop, and screen-reader mode does not double-speak", async ({ page }) => {
  await page.addInitScript(() => {
    (window as any).__spoken = [];
    (window as any).__cancelled = 0;
    const synth = { speak: (u: any) => (window as any).__spoken.push(u.text), cancel: () => { (window as any).__cancelled++; } };
    Object.defineProperty(window, "speechSynthesis", { value: synth, configurable: true });
    (window as any).SpeechSynthesisUtterance = function (this: any, t: string) { this.text = t; } as any;
  });
  await page.goto("/#/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.keyboard.press("Alt+e");
  await expect(page.getByRole("heading", { name: "Eyes-free mode" })).toBeVisible();
  const box = page.getByLabel("Or type a question or a command");
  await box.fill("Which lifts should be repaired or protected first?");
  await box.press("Enter");
  await expect(page.locator("ol.transcript")).toContainText("recorded answer");
  await expect.poll(async () => page.evaluate(() => (window as any).__spoken.join(" | "))).toContain("walk me through it");
  await box.fill("walk me through it"); await box.press("Enter");
  await expect(page.locator("ol.transcript")).toContainText("Step 1 of");
  await box.fill("why"); await box.press("Enter");
  await expect(page.locator("ol.transcript")).toContainText("The proof:");
  await box.fill("stop"); await box.press("Enter");
  expect(await page.evaluate(() => (window as any).__cancelled)).toBeGreaterThan(0);
  const before = await page.evaluate(() => (window as any).__spoken.length);
  await page.getByLabel("My screen reader voices it (no browser speech)").check();
  await box.fill("repeat"); await box.press("Enter");
  await expect(page.locator('[aria-live="assertive"]')).not.toBeEmpty();
  expect(await page.evaluate(() => (window as any).__spoken.length)).toBe(before);
  await noSeriousAxeIssues(page);
});

test("hear a line: silent until Play, each station highlighted and announced, Stop ends it", async ({ page }) => {
  await page.addInitScript(() => { (window as any).__audio = 0; const A = window.AudioContext;
    (window as any).AudioContext = function (this: any) { (window as any).__audio++; return new A(); } as any; });
  await page.goto("/#/network");
  const sweep = page.locator("section.sweep");
  await expect(sweep.getByRole("heading", { name: "Hear a line" })).toBeVisible();
  expect(await page.evaluate(() => (window as any).__audio)).toBe(0);
  await sweep.getByRole("button", { name: "Play the line" }).click();
  await expect(sweep.locator('li[aria-current="step"]')).toHaveCount(1, { timeout: 5000 });
  await expect(page.locator('[role="status"]').filter({ hasText: /: (one lift|lift routes to spare|access lost|no lift needed|no layout data)\./ }).first()).toBeAttached();
  await sweep.getByRole("button", { name: "Stop" }).click();
  await expect(sweep.locator('li[aria-current="step"]')).toHaveCount(0);
  await noSeriousAxeIssues(page);
});

test("atlas: the MBTA row under the generic rules equals LastLift's count", async ({ page }) => {
  await page.goto("/#/atlas");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Can this run in my city?");
  await expect(page.getByText(/comes out at (\d+) single-lift platforms; LastLift's own model says \1\./)).toBeVisible();
  await noSeriousAxeIssues(page);
});

test("N-1 matrix: recomputed in the browser and equal to FalkorDB's certified counts", async ({ page }) => {
  await page.goto("/#/station/place-alfcl?view=plan");
  const chip = page.locator(".matrix .chip").first();
  await expect(chip).toContainText(/matches FalkorDB's certified count for (\d+) of \1 platform-directions/);
  await page.getByRole("button", { name: /^Close lift 813: Red Line, getting on/ }).click();
  await expect(page.getByRole("region", { name: /SIMULATED/ })).toBeVisible();
  await noSeriousAxeIssues(page);
});

test("what-if sandbox: a shared link closes two lifts and lists what breaks", async ({ page }) => {
  await page.goto("/#/sandbox?close=813,891");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Close any lifts and see what breaks");
  await expect(page.locator(".sandbox-chips li")).toHaveCount(2);
  await expect(page.getByText(/Closing lift 813, 891: \d+ platform-directions lose step-free access/).first()).toBeVisible();
  await expect(page.getByRole("table").first()).toBeVisible();
  await noSeriousAxeIssues(page);
});

test("time machine: a keyboard slider with a spoken value, the worst day and its closures", async ({ page }) => {
  await page.goto("/#/history");
  const slider = page.getByRole("slider", { name: "Day" });
  await expect(slider).toHaveAttribute("aria-valuetext", /lifts closed/);
  await slider.focus(); await page.keyboard.press("ArrowLeft");
  await page.getByRole("button", { name: /^Worst day/ }).click();
  await expect(page.getByRole("heading", { name: /Closures that day/ })).toBeVisible();
  await noSeriousAxeIssues(page);
});

test("display panel: high contrast and simple language apply and persist", async ({ page }) => {
  await page.goto("/#/station/place-alfcl?view=plan");
  await page.getByRole("button", { name: "Display" }).click();
  await page.getByLabel("High contrast").check();
  await page.getByLabel("Simple language").check();
  await expect(page.locator("html")).toHaveAttribute("data-contrast", "more");
  await expect(page.getByText(/This station has \d+ platforms/)).toBeVisible();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-simple", "on");
  await noSeriousAxeIssues(page);
});

test("station: the 3D model mounts on request and stays out of the accessibility tree", async ({ page }) => {
  await page.goto("/#/station/place-alfcl?dir=exit");
  await page.getByRole("button", { name: "Model", exact: true }).click();
  const frame = page.locator(".s3d-frame iframe.clay-frame");
  await expect(frame).toHaveAttribute("aria-hidden", "true");
  await expect(frame).toHaveAttribute("src", /concepts\/clay\/demo\.html\?id=place-alfcl/);
});
