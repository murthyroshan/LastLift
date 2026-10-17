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
  await expect(page.locator(".count")).toContainText(/\d+ of \d+/);
  await expect(page.getByRole("table")).toBeVisible();
  await noSeriousAxeIssues(page);
});

test("station view, linked selection and what-if work from the mirror", async ({ page }) => {
  await page.goto("/#/station/place-alfcl?dir=exit");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Alewife");
  await page.getByRole("button", { name: "Red Line" }).click();
  await expect(page.getByRole("button", { name: "Red Line" })).toHaveAttribute("aria-pressed", "true");
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
  expect(asked).toContain("current_closures:live");
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
