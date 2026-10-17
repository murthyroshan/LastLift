import { defineConfig, devices } from "@playwright/test";

// Runs against the production build with the API unreachable on purpose: every core screen must work from
// the static mirror alone, and axe must find no serious or critical issue.
export default defineConfig({
  testDir: "tests",
  timeout: 30_000,
  use: { baseURL: "http://localhost:4173", ...devices["Desktop Chrome"] },
  webServer: {
    command: "npx vite preview --port 4173 --strictPort",
    url: "http://localhost:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
