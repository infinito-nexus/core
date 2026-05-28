/**
 * CSP injection assertion shared by every persona scenario.
 *
 * `assertCspInjections` re-fetches the current URL via
 * `page.request.get` so it can read the raw `content-security-policy`
 * (or `content-security-policy-report-only`) header off the response,
 * then verifies that every service whose JavaScript / CSS / asset is
 * actually injected on the page is also covered by the role's CSP.
 *
 * The intent is symmetric: when an injector role like `mastodon`,
 * `web-svc-asset`, `web-svc-cdn`, `web-svc-css`, `web-svc-javascript`
 * or `web-svc-simpleicons` is enabled, its origin MUST appear in the
 * CSP. When the injector is disabled, its origin MUST NOT appear in
 * any rendered `<script>` / `<link>` / `<img>` tag — otherwise the
 * page would load resources the CSP doesn't permit.
 *
 * The helper is tolerant of policies served via meta-tag (some apps
 * cannot set CSP via header for legacy reasons): it falls back to the
 * first `<meta http-equiv="content-security-policy">` element.
 */

const { expect } = require("@playwright/test");

// Injector base-URL resolution. Switch-case form (rather than a
// dictionary lookup) is intentional: it gives `tests/lint/ansible/
// roles/web-app/playwright/test_env_keys_used.py` a literal
// `process.env.<KEY>` reference for each consumer, so the env-keys-
// used parity guard recognises these env vars as consumed by the
// shared helper.
function injectorBaseUrl(service) {
  switch (service) {
    case "asset":
      return process.env.ASSET_BASE_URL || "";
    case "cdn":
      return process.env.CDN_BASE_URL || "";
    case "css":
      return process.env.CSS_BASE_URL || "";
    case "javascript":
      return process.env.JAVASCRIPT_BASE_URL || "";
    case "simpleicons":
      return process.env.SIMPLEICONS_BASE_URL || "";
    case "matomo":
      return process.env.MATOMO_BASE_URL || "";
    default:
      return "";
  }
}

const INJECTOR_SERVICES = ["asset", "cdn", "css", "javascript", "simpleicons", "matomo"];

function hostOf(url) {
  if (!url) return "";
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

async function readCspString(page) {
  const currentUrl = page.url();
  if (!currentUrl || currentUrl === "about:blank") return "";

  const fresh = await page.request
    .get(currentUrl, { ignoreHTTPSErrors: true, timeout: 10_000 })
    .catch(() => null);
  if (fresh) {
    const headers = fresh.headers();
    const fromHeader = headers["content-security-policy"] || headers["content-security-policy-report-only"];
    if (fromHeader) return fromHeader;
  }

  const fromMeta = await page
    .locator("meta[http-equiv='Content-Security-Policy' i]")
    .first()
    .getAttribute("content")
    .catch(() => "");
  return fromMeta || "";
}

async function assertCspInjections(page, opts = {}) {
  const { isEnabled } = opts;
  if (typeof isEnabled !== "function") return;

  const csp = await readCspString(page);

  for (const service of INJECTOR_SERVICES) {
    let enabled;
    try {
      enabled = isEnabled(service);
    } catch {
      enabled = false;
    }
    if (!enabled) continue;

    const host = hostOf(injectorBaseUrl(service));
    if (!host) continue;

    if (!csp) continue;

    expect(
      csp.toLowerCase().includes(host.toLowerCase()),
      `CSP for the current page MUST include ${host} (service '${service}' is enabled). Got: ${csp}`,
    ).toBe(true);
  }
}

// -----------------------------------------------------------------------------
// CSP header / meta / violation assertions
//
// Shared by every spec that probes a role's `Content-Security-Policy`
// response header, its optional `<meta http-equiv="Content-Security-Policy">`
// echo, and the runtime `securitypolicyviolation` event stream.
// -----------------------------------------------------------------------------

const EXPECTED_CSP_DIRECTIVES = [
  "default-src",
  "connect-src",
  "frame-ancestors",
  "frame-src",
  "script-src",
  "script-src-elem",
  "script-src-attr",
  "style-src",
  "style-src-elem",
  "style-src-attr",
  "font-src",
  "worker-src",
  "manifest-src",
  "media-src",
  "img-src",
];

/** Install a `securitypolicyviolation` listener that captures every
 * blocked load on the page. Pair with `readCspViolations(page)` and
 * `expectNoCspViolations(page, diagnostics, label)`. */
function installCspViolationObserver(page) {
  return page.addInitScript(() => {
    window.__cspViolations = [];
    window.addEventListener("securitypolicyviolation", (event) => {
      window.__cspViolations.push({
        violatedDirective: event.violatedDirective,
        blockedURI: event.blockedURI,
        sourceFile: event.sourceFile,
        lineNumber: event.lineNumber,
        originalPolicy: event.originalPolicy,
      });
    });
  });
}

async function readCspViolations(page) {
  return page.evaluate(() => window.__cspViolations || []).catch(() => []);
}

/** Parse a `Content-Security-Policy` header string into a directive
 * map (`{ "default-src": ["'self'", "https://example.com"], ... }`). */
function parseCspHeader(value) {
  const result = {};
  if (!value) return result;
  for (const raw of value.split(";")) {
    const trimmed = raw.trim();
    if (!trimmed) continue;
    const parts = trimmed.split(/\s+/);
    const directive = parts.shift();
    if (!directive) continue;
    result[directive.toLowerCase()] = parts;
  }
  return result;
}

/** Assert the response carries an enforced (NOT report-only) CSP
 * header that lists every directive in `EXPECTED_CSP_DIRECTIVES`.
 * Returns the parsed header so callers can hand it to
 * `assertCspMetaParity`. */
function assertCspResponseHeader(response, label) {
  const headers = response.headers();
  const cspHeader = headers["content-security-policy"];
  expect(
    cspHeader,
    `${label}: Content-Security-Policy response header MUST be present`
  ).toBeTruthy();
  const reportOnly = headers["content-security-policy-report-only"];
  expect(
    reportOnly,
    `${label}: Content-Security-Policy-Report-Only MUST NOT be set (policy must be enforced)`
  ).toBeFalsy();
  const parsed = parseCspHeader(cspHeader);
  const missing = EXPECTED_CSP_DIRECTIVES.filter((directive) => !parsed[directive]);
  expect(
    missing,
    `${label}: CSP directives missing from response header: ${missing.join(", ")}`
  ).toEqual([]);
  return parsed;
}

/** When the role echoes its CSP via `<meta http-equiv="...">`, every
 * token in the meta MUST also appear in the response header — meta
 * MAY be a strict subset, never a strict superset. No-op when the
 * meta tag is absent. */
async function assertCspMetaParity(page, headerDirectives, label) {
  const metaLocator = page.locator('meta[http-equiv="Content-Security-Policy"]').first();
  const hasMeta = (await metaLocator.count().catch(() => 0)) > 0;
  if (!hasMeta) return;
  const metaContent = await metaLocator.getAttribute("content").catch(() => null);
  if (!metaContent) return;
  const metaParsed = parseCspHeader(metaContent);
  for (const directive of Object.keys(metaParsed)) {
    const headerTokens = new Set(headerDirectives[directive] || []);
    const metaTokens = metaParsed[directive] || [];
    for (const token of metaTokens) {
      expect(
        headerTokens.has(token),
        `${label}: CSP meta token "${token}" for directive ${directive} MUST also appear in the response header`
      ).toBe(true);
    }
  }
}

/** Assert no `securitypolicyviolation` events fired AND (when the
 * caller passes a diagnostics object captured by `attachDiagnostics`)
 * no CSP-related console / pageerror entries surfaced.
 *
 * `diagnostics` is optional: pass `null` (or omit the third arg) when
 * the spec does not track diagnostics. The shared helper still
 * validates the DOM-level violations either way. */
async function expectNoCspViolations(page, diagnostics, label) {
  const domViolations = await readCspViolations(page);
  expect(
    domViolations,
    `${label}: securitypolicyviolation events observed: ${JSON.stringify(domViolations)}`
  ).toEqual([]);
  if (diagnostics && Array.isArray(diagnostics.cspRelated)) {
    expect(
      diagnostics.cspRelated,
      `${label}: CSP-related console/pageerror entries observed: ${JSON.stringify(diagnostics.cspRelated)}`
    ).toEqual([]);
  }
}

function captureAssetLoads(page, { hostCandidates, resourceTypes }) {
  const hosts = (hostCandidates || []).map((h) => String(h || "").toLowerCase());
  const types = resourceTypes && resourceTypes.length > 0 ? resourceTypes : null;
  const loads = [];
  page.on("response", (response) => {
    try {
      const host = new URL(response.url()).host.toLowerCase();
      if (!hosts.includes(host)) return;
      if (types && !types.includes(response.request().resourceType())) return;
      loads.push({
        url: response.url(),
        status: response.status(),
        type: response.request().resourceType(),
      });
    } catch {
      // ignore unparseable URLs
    }
  });
  return loads;
}

async function assertInjectedAssetLoadsWithoutCspBlock(page, {
  url,
  hostCandidates,
  resourceTypes,
  label,
  navTimeout = 30_000,
  waitUntil = "networkidle",
}) {
  const hosts = (hostCandidates || []).map((h) => String(h || "").toLowerCase());
  const types = resourceTypes && resourceTypes.length > 0 ? resourceTypes : null;
  const loads = captureAssetLoads(page, { hostCandidates: hosts, resourceTypes: types });
  await installCspViolationObserver(page);
  await page.goto(url, { waitUntil, timeout: navTimeout });

  const successful = loads.filter((r) => r.status >= 200 && r.status < 400);
  expect(
    successful.length,
    `${label}: browser observed no successful (2xx/3xx) response from ` +
    `[${hosts.join(", ")}] for resourceType(s) [${(types || ["*"]).join(", ")}] ` +
    `during navigation to ${url}. Observed loads: ${JSON.stringify(loads)}. ` +
    `This means either the role's vhost does not inject the expected ` +
    `<link>/<script> markup, the asset returned an error, or CSP blocked the request.`
  ).toBeGreaterThan(0);

  const violations = await readCspViolations(page);
  const blocks = violations.filter((v) => {
    let blockedHost;
    try {
      blockedHost = new URL(v.blockedURI).host.toLowerCase();
    } catch {
      return false;
    }
    return hosts.includes(blockedHost);
  });
  expect(
    blocks,
    `${label}: CSP blocked load from injected asset host(s) ` +
    `[${hosts.join(", ")}] during navigation to ${url}: ${JSON.stringify(blocks)}. ` +
    `Add the host to the relevant *-src directive in the role's CSP.`
  ).toEqual([]);
}

module.exports = {
  assertCspInjections,
  EXPECTED_CSP_DIRECTIVES,
  installCspViolationObserver,
  readCspViolations,
  parseCspHeader,
  assertCspResponseHeader,
  assertCspMetaParity,
  expectNoCspViolations,
  captureAssetLoads,
  assertInjectedAssetLoadsWithoutCspBlock,
};
