/**
 * Env-handling utilities shared by every persona-flow module.
 *
 * Kept tiny and dependency-free so each module can `require` only
 * what it needs.
 */

const { test } = require("@playwright/test");
const { isServiceEnabled } = require("../../service-gating");

function decodeDotenvQuoted(value) {
  if (typeof value !== "string" || value.length < 2) return value;
  if (!(value.startsWith('"') && value.endsWith('"'))) return value;
  const encoded = value.slice(1, -1);
  try {
    return JSON.parse(`"${encoded}"`).replace(/\$\$/g, "$");
  } catch {
    return encoded.replace(/\$\$/g, "$");
  }
}

function normalizeUrl(value) {
  return decodeDotenvQuoted(value || "").replace(/\/$/, "");
}

function readEnv(name) {
  return decodeDotenvQuoted(process.env[name] || "");
}

/** True when the role under test is served over a `.onion` (Tor) canonical domain. */
function isOnionCanonical() {
  return /\.onion$/i.test(readEnv("CANONICAL_DOMAIN").trim());
}

/**
 * Tor-resilient `page.goto`: retries only transient Tor-transport errors
 * (`ERR_TIMED_OUT` / `ERR_SOCKS…`); real navigation failures re-throw on the
 * first hit. Clearnet URLs get a single attempt; callers budget the test
 * timeout for the onion retries.
 */
const _ONION_TRANSIENT_RE =
  /ERR_TIMED_OUT|ERR_SOCKS|ERR_CONNECTION_(?:CLOSED|RESET|FAILED)|ERR_PROXY_CONNECTION_FAILED|ERR_EMPTY_RESPONSE|ERR_TUNNEL_CONNECTION_FAILED/i;

async function gotoOnion(page, url, opts = {}) {
  const isRelative = /^\/(?!\/)/.test(url);
  const isOnion =
    /\.onion(?::\d+)?(?:\/|$|\?)/i.test(url) || (isRelative && isOnionCanonical());
  const attempts = isOnion ? Number(process.env.PLAYWRIGHT_ONION_GOTO_RETRIES) || 4 : 1;
  const gotoOpts = { ...opts };
  if (isOnion && gotoOpts.timeout === undefined) {
    gotoOpts.timeout = Number(process.env.PLAYWRIGHT_NAVIGATION_TIMEOUT) || 60_000;
  }
  // Heavy SPAs (Element) fetch 30+ chunked JS bundles; over Tor each request
  // serialises circuit latency, so the `load` event (every lazy subresource)
  // can exceed the navigation cap. `domcontentloaded` returns after the HTML
  // parses; the caller's explicit selector waits (onion-scaled) cover app boot.
  if (isOnion && gotoOpts.waitUntil === undefined) {
    gotoOpts.waitUntil = "domcontentloaded";
  }
  let lastErr;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await page.goto(url, gotoOpts);
    } catch (err) {
      lastErr = err;
      if (attempt >= attempts || !_ONION_TRANSIENT_RE.test(String(err && err.message))) {
        throw err;
      }
      await page.waitForTimeout(2_000 * attempt);
    }
  }
  throw lastErr;
}

/**
 * Tolerant variant of `skipUnlessServiceEnabled`: treats an unknown
 * service (i.e. one whose `<NAME>_SERVICE_ENABLED` flag is not declared
 * in the role's env registry) as "disabled" rather than a hard fail.
 * Roles MAY mark a service entry with `# nocheck: playwright-service-flag`
 * in `meta/services.yml`, in which case the env flag is not rendered
 * and the gate MUST skip cleanly.
 */
function safeSkipUnlessEnabled(name) {
  let enabled;
  try {
    enabled = isServiceEnabled(name);
  } catch {
    enabled = false;
  }
  if (!enabled) {
    test.skip(true, `${name.toUpperCase()}_SERVICE_ENABLED=false or unknown`);
  }
}

function safeIsEnabled(name) {
  try {
    return isServiceEnabled(name);
  } catch {
    return false;
  }
}

module.exports = {
  decodeDotenvQuoted,
  normalizeUrl,
  readEnv,
  isOnionCanonical,
  gotoOnion,
  safeSkipUnlessEnabled,
  safeIsEnabled,
};
