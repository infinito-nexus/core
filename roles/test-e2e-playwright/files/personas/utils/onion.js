/**
 * Tor-resilient navigation and request helpers.
 */

const { resolveTimeout } = require("../../timeouts");
const { installCspHeaderRecorder } = require("./csp");
const { readEnv } = require("./env");

function isOnionCanonical() {
  return /\.onion$/i.test(readEnv("CANONICAL_DOMAIN").trim());
}

function isOnionUrl(url) {
  const isRelative = /^\/(?!\/)/.test(url);
  return (
    /\.onion(?::\d+)?(?:\/|$|\?)/i.test(url) || (isRelative && isOnionCanonical())
  );
}

function onionAttempts(isOnion) {
  return isOnion ? Number(process.env.PLAYWRIGHT_ONION_GOTO_RETRIES) || 4 : 1;
}

/**
 * Tor-resilient `page.goto`: retries only transient Tor-transport errors;
 * real navigation failures re-throw on the first hit. Clearnet URLs get a
 * single attempt; callers budget the test timeout for the onion retries.
 */
const _ONION_TRANSIENT_RE =
  /ERR_TIMED_OUT|ERR_SOCKS|ERR_CONNECTION_(?:CLOSED|RESET|FAILED)|ERR_PROXY_CONNECTION_FAILED|ERR_EMPTY_RESPONSE|ERR_TUNNEL_CONNECTION_FAILED|NS_ERROR_NET_(?:TIMEOUT|RESET|INTERRUPT)|NS_ERROR_(?:CONNECTION_REFUSED|UNKNOWN_HOST|PROXY_CONNECTION_REFUSED|UNKNOWN_PROXY_HOST)|NS_BINDING_ABORTED|Load request cancelled|page\.goto: Timeout \d+ms exceeded/i;

async function gotoOnion(page, url, opts = {}) {
  installCspHeaderRecorder(page);
  const isOnion = isOnionUrl(url);
  const attempts = onionAttempts(isOnion);
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
      await page.waitForTimeout(resolveTimeout(2_000 * attempt));
    }
  }
  throw lastErr;
}

/**
 * Wait for a click-triggered navigation to land on *expected*, retrying the
 * handoff while the browser is parked on a failed navigation.
 *
 * Args:
 *   page: the Playwright page.
 *   expected: substring the target URL must contain.
 *   reissue: async callback that triggers the navigation again.
 *   opts.timeout: per-attempt budget, already onion-scaled by the caller.
 */
async function awaitOnionHandoff(page, expected, reissue, opts = {}) {
  const attempts = onionAttempts(true);
  const timeout = opts.timeout || resolveTimeout(60_000);
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      await page.waitForURL((url) => String(url).includes(expected), { timeout });
      return;
    } catch (err) {
      if (attempt >= attempts || !page.url().startsWith("chrome-error://")) {
        throw err;
      }
      await page.waitForTimeout(resolveTimeout(2_000 * attempt));
      await reissue();
    }
  }
}

/**
 * Tor-resilient `request.fetch` for any APIRequestContext (the standalone
 * fixture or `context.request`); `opts.method` picks the verb. Its SOCKS
 * CONNECT goes through the bundled `socks` client whose 30s connect cap is not
 * configurable, so a cold onion circuit fails the request no matter how large
 * the request timeout is. Retries only transient proxy/socket errors; clearnet
 * URLs get a single attempt and real HTTP failures re-throw. `apiGetOnion` is
 * the GET shorthand.
 */
const _API_TRANSIENT_RE =
  /Proxy connection timed out|Socks5 proxy rejected connection|Socket closed|socket hang up|ECONNRESET|ETIMEDOUT|ECONNREFUSED|ENOTFOUND/i;

function apiGetOnion(request, url, opts = {}) {
  return apiFetchOnion(request, url, { ...opts, method: "GET" });
}

async function apiFetchOnion(request, url, opts = {}) {
  const attempts = onionAttempts(isOnionUrl(url));
  let lastErr;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await request.fetch(url, opts);
    } catch (err) {
      lastErr = err;
      if (attempt >= attempts || !_API_TRANSIENT_RE.test(String(err && err.message))) {
        throw err;
      }
      await new Promise((resolve) => setTimeout(resolve, resolveTimeout(2_000 * attempt)));
    }
  }
  throw lastErr;
}

module.exports = {
  isOnionCanonical,
  isOnionUrl,
  gotoOnion,
  awaitOnionHandoff,
  apiGetOnion,
  apiFetchOnion,
};
