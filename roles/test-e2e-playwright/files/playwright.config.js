const { defineConfig } = require("@playwright/test");

const baseURL = process.env.APP_BASE_URL || "http://127.0.0.1";

const keepAll = (process.env.INFINITO_PLAYWRIGHT_KEEP || "").toLowerCase() === "true";

module.exports = defineConfig({
  testDir: "./tests",
  testMatch: "**/*.@(spec|test).js",
  timeout: Number(process.env.PLAYWRIGHT_TEST_TIMEOUT) || 300_000,
  retries: 2,
  workers: Number(process.env.PLAYWRIGHT_WORKERS) || 1,
  fullyParallel: (process.env.PLAYWRIGHT_FULLY_PARALLEL || "").toLowerCase() === "true",
  outputDir: "/reports/test-results",
  reporter: [
    ["list"],
    // `github` emits ::error file=...,line=...::-annotations for failed
    // tests when the runner exports GITHUB_ACTIONS=true, which surfaces
    // failures inline on the workflow run page.
    ["github"],
    ["junit", { outputFile: "/reports/playwright-junit.xml" }],
    ["html", { outputFolder: "/reports/playwright-report", open: "never" }]
  ],
  use: {
    baseURL,
    // Route the browser through a SOCKS proxy when set (e.g. Tor for .onion
    // targets, which Chromium cannot resolve over normal DNS). Empty/unset =
    // direct connection (unchanged default for clearnet targets).
    proxy: process.env.PLAYWRIGHT_PROXY ? { server: process.env.PLAYWRIGHT_PROXY } : undefined,
    // Fail fast instead of hanging until the per-test timeout when a target is
    // unreachable (e.g. an onion service that is not yet published).
    navigationTimeout: Number(process.env.PLAYWRIGHT_NAVIGATION_TIMEOUT) || 60_000,
    actionTimeout: Number(process.env.PLAYWRIGHT_ACTION_TIMEOUT) || 30_000,
    trace: keepAll ? "on" : "retain-on-failure",
    screenshot: keepAll ? "on" : "only-on-failure",
    video: keepAll ? "on" : "retain-on-failure"
  }
});
