const { defineConfig } = require("@playwright/test");

const baseURL = process.env.APP_BASE_URL || "http://127.0.0.1";

const keepAll = (process.env.INFINITO_PLAYWRIGHT_KEEP || "").toLowerCase() === "true";

module.exports = defineConfig({
  testDir: "./tests",
  timeout: 300_000,
  retries: 2,
  workers: 1,
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
    trace: keepAll ? "on" : "retain-on-failure",
    screenshot: keepAll ? "on" : "only-on-failure",
    video: keepAll ? "on" : "retain-on-failure"
  }
});
