const { defineConfig } = require("@playwright/test");

// nocheck: env-default  a role may export its own base variable and no APP_BASE_URL
const baseURL = process.env.APP_BASE_URL || "http://127.0.0.1";

const keepAll = (process.env.INFINITO_PLAYWRIGHT_KEEP || "").toLowerCase() === "true";

function onionSecureOrigins() {
  const origins = new Set();
  for (const value of Object.values(process.env)) {
    if (typeof value !== "string") continue;
    for (const match of value.match(/https?:\/\/[^/,\s"']+\.onion/gi) || []) {
      try {
        origins.add(new URL(match).origin);
      } catch {
        /* not a parseable URL — skip */
      }
    }
  }
  return [...origins];
}

const onionSecure = onionSecureOrigins();

/**
 * The timeout the harness renders into the staged .env under this name.
 *
 * Args:
 *   name: the PLAYWRIGHT_*_TIMEOUT variable to read.
 */
function requiredTimeout(name) {
  const value = Number(process.env[name]);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(
      `${name} is missing from the environment. The harness writes every ` +
        "timeout into the staged .env, so this run was started outside it."
    );
  }
  return value;
}

const globalTimeout = parseInt(process.env.INFINITO_PLAYWRIGHT_GLOBAL_TIMEOUT_MS || 0, 10);

module.exports = defineConfig({
  testDir: "./tests",
  testMatch: "**/*.@(spec|test).js",
  timeout: requiredTimeout("PLAYWRIGHT_TEST_TIMEOUT"),
  expect: { timeout: requiredTimeout("PLAYWRIGHT_EXPECT_TIMEOUT") },
  ...(globalTimeout > 0 ? { globalTimeout } : {}),
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
    launchOptions: onionSecure.length
      ? { args: [`--unsafely-treat-insecure-origin-as-secure=${onionSecure.join(",")}`] }
      : undefined,
    // Fail fast instead of hanging until the per-test timeout when a target is
    // unreachable (e.g. an onion service that is not yet published).
    navigationTimeout: requiredTimeout("PLAYWRIGHT_NAVIGATION_TIMEOUT"),
    actionTimeout: requiredTimeout("PLAYWRIGHT_ACTION_TIMEOUT"),
    trace: keepAll ? "on" : "retain-on-failure",
    screenshot: keepAll ? "on" : "only-on-failure",
    video: keepAll ? "on" : "retain-on-failure"
  }
});
