const fs = require("fs");
const { defineConfig } = require("@playwright/test");
const { torOrigins } = require("./tests/personas/utils/network");

// nocheck: env-default  a role may export its own base variable and no APP_BASE_URL
const baseURL = process.env.APP_BASE_URL || "http://127.0.0.1";

const keepAll = (process.env.INFINITO_PLAYWRIGHT_KEEP || "").toLowerCase() === "true";

const captureOff =
  fs.existsSync("/run/spec-secrets") ||
  (process.env.INFINITO_PLAYWRIGHT_NO_CAPTURE || "").toLowerCase() === "true";

const capture = captureOff
  ? { trace: "off", screenshot: "off", video: "off" }
  : {
      trace: keepAll ? "on" : "retain-on-failure",
      screenshot: keepAll ? "on" : "only-on-failure",
      video: keepAll ? "on" : "retain-on-failure"
    };

const recordingEnv = ["PW_TEST_REPORTER", "PLAYWRIGHT_LIST_PRINT_STEPS", "PLAYWRIGHT_DASHBOARD", "DEBUG", "DEBUG_FILE"];

const reporterEnv = /^PLAYWRIGHT_(JUNIT|JSON|HTML|BLOB)_/;

if (captureOff) {
  process.env.PLAYWRIGHT_NO_COPY_PROMPT = "1";
  for (const name of Object.keys(process.env)) {
    if (recordingEnv.includes(name) || reporterEnv.test(name)) {
      delete process.env[name];
    }
  }
}

const onionSecure = torOrigins(Object.values(process.env));

const proxy = process.env.PLAYWRIGHT_PROXY
  ? {
      server: process.env.PLAYWRIGHT_PROXY,
      ...(process.env.PLAYWRIGHT_PROXY_BYPASS
        ? { bypass: process.env.PLAYWRIGHT_PROXY_BYPASS }
        : {}),
    }
  : undefined;

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
  workers: Math.min(
    Number(process.env.PLAYWRIGHT_WORKERS) || 1,
    Number(process.env.PLAYWRIGHT_MAX_WORKERS) || Infinity
  ),
  fullyParallel: (process.env.PLAYWRIGHT_FULLY_PARALLEL || "").toLowerCase() === "true",
  outputDir: captureOff ? "/tmp/test-results" : "/reports/test-results",
  ...(captureOff ? { updateSnapshots: "none" } : {}),
  reporter: [
    ["list"],
    // `github` emits ::error file=...,line=...::-annotations for failed
    // tests when the runner exports GITHUB_ACTIONS=true, which surfaces
    // failures inline on the workflow run page.
    ["github"],
    ["junit", { outputFile: "/reports/playwright-junit.xml" }],
    ...(captureOff ? [] : [["html", { outputFolder: "/reports/playwright-report", open: "never" }]])
  ],
  use: {
    baseURL,
    // Route the browser through a SOCKS proxy when set (e.g. Tor for .onion
    // targets, which Chromium cannot resolve over normal DNS). Empty/unset =
    // direct connection (unchanged default for clearnet targets).
    proxy,
    ...(onionSecure.length
      ? {
          channel: "chromium",
          launchOptions: {
            args: [`--unsafely-treat-insecure-origin-as-secure=${onionSecure.join(",")}`],
          },
        }
      : {}),
    // Fail fast instead of hanging until the per-test timeout when a target is
    // unreachable (e.g. an onion service that is not yet published).
    navigationTimeout: requiredTimeout("PLAYWRIGHT_NAVIGATION_TIMEOUT"),
    actionTimeout: requiredTimeout("PLAYWRIGHT_ACTION_TIMEOUT"),
    ...capture
  }
});
