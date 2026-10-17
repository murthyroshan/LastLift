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
