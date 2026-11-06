const { expect } = require("@playwright/test");
const { decodeDotenvQuotedValue, normalizeBaseUrl, gotoOnion, performKeycloakLoginForm } = require("./personas");
const { resolveTimeout } = require("./timeouts");
const keycloakAdmin = require("./personas/utils/keycloak");

const SESSION_COOKIE = "grafana_session";

const env = {
  appBaseUrl: normalizeBaseUrl(process.env.APP_BASE_URL || "").replace(/\/$/, ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN),
  cdnRelativeRoot: decodeDotenvQuotedValue(process.env.CDN_RELATIVE_ROOT),
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  keycloakAdminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM),
  keycloakAdminCliClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  auditorGroupPath: decodeDotenvQuotedValue(process.env.RBAC_AUDITOR_GROUP_PATH),
  lokiUid: decodeDotenvQuotedValue(process.env.LOKI_DATASOURCE_UID),
  prometheusUid: decodeDotenvQuotedValue(process.env.PROMETHEUS_DATASOURCE_UID),
  probeApplication: decodeDotenvQuotedValue(process.env.LOG_PROBE_APPLICATION),
  alertTitle: decodeDotenvQuotedValue(process.env.LOG_ALERT_TITLE),
  alertReceiver: decodeDotenvQuotedValue(process.env.LOG_ALERT_RECEIVER),
};

const LOG_PROBE_SEGMENT = "infinito-log-probe";

/**
 * Whether the browser context of `page` holds a Grafana session.
 *
 * Args:
 *   page: the Playwright page whose context is inspected.
 */
async function hasGrafanaSession(page) {
  const cookies = await page.context().cookies(env.appBaseUrl);
  return cookies.some((cookie) => cookie.name === SESSION_COOKIE);
}

/**
 * Sign in through Grafana's generic OAuth auto-login and wait for a session.
 *
 * Args:
 *   page: the Playwright page to drive.
 *   username: the Keycloak login name.
 *   password: the Keycloak password.
 */
async function loginViaOidc(page, username, password) {
  await gotoOnion(page, `${env.appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected Grafana to redirect to Keycloak" })
    .toContain("openid-connect/auth");
  await performKeycloakLoginForm(page, username, password);
  await expect
    .poll(() => hasGrafanaSession(page), {
      timeout: resolveTimeout(90_000),
      message: `expected ${username} to receive a Grafana session`,
    })
    .toBe(true);
}

/**
 * Run `fn` while biber is a member of the Keycloak group at `groupPath`,
 * removing the membership afterwards only when this call granted it.
 *
 * Args:
 *   browser: the Playwright browser, used for an isolated admin context.
 *   groupPath: the full Keycloak group path, with leading slash.
 *   fn: async body executed while the membership holds.
 */
async function withBiberInGroup(browser, groupPath, fn) {
  const adminOpts = { adminRealm: env.keycloakAdminRealm, adminClientId: env.keycloakAdminCliClientId };
  const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
  let biberAdded = false;
  try {
    biberAdded = await keycloakAdmin.keycloakAdminAddUserToGroup(
      adminCtx.request,
      env.keycloakBaseUrl,
      env.realmName,
      groupPath,
      env.biberUsername,
      env.superAdminUsername,
      env.superAdminPassword,
      adminOpts,
    );
    return await fn();
  } finally {
    if (biberAdded) {
      await keycloakAdmin
        .keycloakRemoveUserFromGroupViaRest(
          adminCtx.request,
          env.keycloakBaseUrl,
          env.realmName,
          env.superAdminUsername,
          env.superAdminPassword,
          groupPath,
          env.biberUsername,
          adminOpts,
        )
        .catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
    }
    await adminCtx.close().catch(() => {});
  }
}

/**
 * A unique probe value and the request path that carries it. The proxy logs
 * the request path without its query string, so the value travels as a path
 * segment.
 *
 * Args:
 *   words: path segments appended after the unique value, e.g. a word the
 *     log alert matches; an empty list yields the bare probe.
 *
 * Returns:
 *   `{ runId, path }`, the path without a leading slash.
 */
function probePath(words) {
  const runId = `probe${Date.now()}${Math.floor(Math.random() * 1_000_000)}`;
  const path = [LOG_PROBE_SEGMENT, runId, ...words].map(encodeURIComponent).join("/");
  return { runId, path };
}

/**
 * Write one access-log line into the reverse proxy's journal and return
 * the unique value it carries. The collector classes it `access`.
 *
 * Args:
 *   page: a Playwright page whose request context sends the probe.
 *   words: see `probePath`.
 */
async function writeProbeLine(page, words) {
  const { runId, path } = probePath(words);
  await page.request.get(`${env.appBaseUrl}/${path}`, {
    failOnStatusCode: false,
    maxRedirects: 0,
    timeout: resolveTimeout(30_000),
  });
  return runId;
}

/**
 * Write one error-log line into the reverse proxy's journal and return the
 * unique value it carries. The request asks the CDN location every vhost
 * serves for a file it does not hold, so the proxy answers 404 and logs the
 * failed open() of that path to stderr, which the collector classes
 * `application`; the access-log line of the same request is classed `access`,
 * which the log alerts do not read.
 *
 * Args:
 *   page: a Playwright page whose request context sends the probe.
 *   words: see `probePath`.
 */
async function writeProbeErrorLine(page, words) {
  const { runId, path } = probePath(words);
  const response = await page.request.get(`${env.appBaseUrl}${env.cdnRelativeRoot}${path}`, {
    failOnStatusCode: false,
    maxRedirects: 0,
    timeout: resolveTimeout(30_000),
  });
  expect(
    response.status(),
    `the proxy MUST answer the missing CDN file ${env.cdnRelativeRoot}${path} with 404, the answer that logs its path to the error log`,
  ).toBe(404);
  return runId;
}

/**
 * The Explore URL that runs `expr` against the Loki datasource.
 *
 * Args:
 *   expr: the LogQL query.
 */
function exploreUrl(expr) {
  const panes = {
    a: {
      datasource: env.lokiUid,
      queries: [{ refId: "A", expr, queryType: "range", datasource: { type: "loki", uid: env.lokiUid } }],
      range: { from: "now-15m", to: "now" },
    },
  };
  return `${env.appBaseUrl}/explore?schemaVersion=1&orgId=1&panes=${encodeURIComponent(JSON.stringify(panes))}`;
}

/**
 * Send a Grafana API request with the session of `page`, as the UI would.
 *
 * Args:
 *   page: a Playwright page whose context carries the Grafana session.
 *   method: HTTP method.
 *   path: API path below the Grafana base URL.
 *   data: JSON body.
 */
async function grafanaApi(page, method, path, data) {
  return page.request.fetch(`${env.appBaseUrl}${path}`, {
    method,
    data,
    headers: { "Content-Type": "application/json", Origin: new URL(env.appBaseUrl).origin },
    failOnStatusCode: false,
    timeout: resolveTimeout(60_000),
  });
}

module.exports = {
  LOG_PROBE_SEGMENT,
  env,
  exploreUrl,
  grafanaApi,
  hasGrafanaSession,
  loginViaOidc,
  withBiberInGroup,
  writeProbeErrorLine,
  writeProbeLine,
};
