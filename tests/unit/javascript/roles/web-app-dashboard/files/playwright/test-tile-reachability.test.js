const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const { DOMAIN } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/domain.js"));

const DASHBOARD = `https://dashboard.${DOMAIN}/`;
const CHROME_ERROR = "chrome-error://chromewebdata/";
const ELEMENT = `https://element.${DOMAIN}/`;
const SYNAPSE_SSO = `https://matrix.${DOMAIN}/_matrix/client/v3/login/sso/redirect?redirectUrl=${encodeURIComponent(`${ELEMENT}#/`)}`;
const KEYCLOAK_AUTH = `https://auth.${DOMAIN}/realms/infinito.nexus/protocol/openid-connect/auth`;
const KEYCLOAK_FOR_SYNAPSE = `${KEYCLOAK_AUTH}?response_type=code&client_id=matrix-synapse&redirect_uri=${encodeURIComponent(`https://matrix.${DOMAIN}/_synapse/client/oidc/callback`)}`;
const PROXIED = `https://prometheus.${DOMAIN}/`;
const PROXY_START = `${PROXIED}oauth2/start?rd=%2F`;
const KEYCLOAK_FOR_PROXY = `${KEYCLOAK_AUTH}?response_type=code&client_id=prometheus&redirect_uri=${encodeURIComponent(`${PROXIED}oauth2/callback`)}`;
const PIHOLE = `https://pihole.${DOMAIN}/`;
const PIHOLE_ADMIN = `${PIHOLE}admin/`;
const MATRIX = { id: "web-app-matrix", canonical_domain: `element.${DOMAIN}`, handover_domain: "" };
const PROMETHEUS = { id: "web-app-prometheus", canonical_domain: `prometheus.${DOMAIN}`, handover_domain: "" };
const PIHOLE_TARGET = { id: "web-app-pihole", canonical_domain: `pihole.${DOMAIN}`, handover_domain: "" };
const ESCAPED_DOMAIN = DOMAIN.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const WALKED_ELEMENT = new RegExp(`Expected the embedded element\\.${ESCAPED_DOMAIN} to answer the new tab`);
const WALKED_PIHOLE = new RegExp(`Expected the embedded pihole\\.${ESCAPED_DOMAIN} to answer the new tab`);
const WALKED_PROMETHEUS = new RegExp(`Expected the embedded prometheus\\.${ESCAPED_DOMAIN} to answer the new tab`);

/**
 * Args:
 *   actual: the value under assertion.
 *   message: the failure message.
 *
 * Returns:
 *   The matchers assertTabButtonOpensNewTab calls, failing like Playwright's with the message.
 */
function expect(actual, message) {
  return {
    toBeVisible: async () => {},
    toBe: (expected) => assert.equal(actual, expected, message),
  };
}

const { assertTabButtonOpensNewTab } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-dashboard/files/playwright/test-tile-reachability.js"),
  ["assertTabButtonOpensNewTab"],
  {
    "./fixtures/onion-test": { test: () => {}, expect },
    "./timeouts": { resolveTimeout: (ms) => ms },
    "./personas": { decodeDotenvJsonList: () => [], gotoOnion: async () => {} },
  },
  { URL },
);

/**
 * Args:
 *   url: the URL the request navigates to.
 *   frame: the frame it navigates; null while Playwright has not announced the page of that frame.
 *
 * Returns:
 *   A navigation request whose frame() throws like Playwright's for an unannounced frame.
 */
function navigation(url, frame) {
  return {
    isNavigationRequest: () => true,
    url: () => url,
    frame: () => {
      if (!frame) {
        throw new Error("Frame for this navigation request is not available");
      }
      return frame;
    },
  };
}

/**
 * Args:
 *   embedded: the ?iframe= value of the dashboard, which window.open hands the new tab.
 *   tabHops: [url, status] per top-level navigation of the new tab, in order; status null sends no response, and the first hop goes out before the tab is announced.
 *   embedHops: [url, status] per navigation of the dashboard's own #main iframe while the tab opens.
 *   landing: the URL the tab shows once its document loaded.
 *
 * Returns:
 *   { page, context, listeners }: a dashboard whose Tab button opens a tab that walks tabHops.
 */
function dashboardWithTab(embedded, tabHops, embedHops, landing) {
  const listeners = { request: new Set(), response: new Set() };
  let announce;
  const announced = new Promise((resolve) => {
    announce = resolve;
  });
  const page = {};
  const popup = { url: () => landing, waitForLoadState: async () => {}, close: async () => {} };
  const popupFrame = { page: () => popup, parentFrame: () => null };
  const embedFrame = { page: () => page, parentFrame: () => ({}) };
  const walk = ([url, status], frame) => {
    const request = navigation(url, frame);
    listeners.request.forEach((listener) => listener(request));
    if (status !== null) {
      listeners.response.forEach((listener) => listener({ request: () => request, status: () => status }));
    }
  };
  const tabButton = {
    isVisible: async () => true,
    click: async () => {
      embedHops.forEach((hop) => walk(hop, embedFrame));
      tabHops.forEach((hop, index) => walk(hop, index === 0 ? null : popupFrame));
      announce(popup);
    },
  };
  Object.assign(page, {
    url: () => `${DASHBOARD}?iframe=${encodeURIComponent(embedded)}`,
    locator: () => ({ first: () => tabButton }),
    evaluate: async () => {},
  });
  const context = {
    on: (event, listener) => listeners[event].add(listener),
    off: (event, listener) => listeners[event].delete(listener),
    waitForEvent: async () => announced,
  };
  return { page, context, listeners };
}

test("a tab whose Element answers and then hands its login through Synapse to Keycloak passes", async () => {
  const { page, context, listeners } = dashboardWithTab(
    ELEMENT,
    [
      [ELEMENT, 200],
      [SYNAPSE_SSO, 302],
      [KEYCLOAK_FOR_SYNAPSE, 200],
    ],
    [],
    KEYCLOAK_FOR_SYNAPSE,
  );
  await assertTabButtonOpensNewTab(page, context, MATRIX);
  assert.equal(listeners.request.size + listeners.response.size, 0, "the tab recorder must detach from the context");
});

test("Element's answer to the tab's first request, sent before Playwright announces the tab, counts", async () => {
  const { page, context } = dashboardWithTab(ELEMENT, [[ELEMENT, 200]], [], ELEMENT);
  await assertTabButtonOpensNewTab(page, context, MATRIX);
});

test("an oauth2-proxy app that redirects the tab to the IdP with a redirect_uri back to it passes", async () => {
  const { page, context } = dashboardWithTab(
    PROXIED,
    [
      [PROXIED, 302],
      [PROXY_START, 302],
      [KEYCLOAK_FOR_PROXY, 200],
    ],
    [],
    KEYCLOAK_FOR_PROXY,
  );
  await assertTabButtonOpensNewTab(page, context, PROMETHEUS);
});

test("a tab the dashboard opens on the IdP login its iframe already reached, returning to the oauth2-proxy app, passes", async () => {
  const { page, context } = dashboardWithTab(
    PROXIED,
    [[KEYCLOAK_FOR_PROXY, 200]],
    [
      [PROXIED, 302],
      [KEYCLOAK_FOR_PROXY, 200],
    ],
    KEYCLOAK_FOR_PROXY,
  );
  await assertTabButtonOpensNewTab(page, context, PROMETHEUS);
});

test("a tab that starts on an IdP login returning to another host fails", async () => {
  const { page, context } = dashboardWithTab(ELEMENT, [[KEYCLOAK_FOR_PROXY, 200]], [], KEYCLOAK_FOR_PROXY);
  await assert.rejects(assertTabButtonOpensNewTab(page, context, MATRIX), WALKED_ELEMENT);
});

test("a tab that starts on an IdP login that never answers fails", async () => {
  const { page, context } = dashboardWithTab(PROXIED, [[KEYCLOAK_FOR_PROXY, null]], [], CHROME_ERROR);
  await assert.rejects(assertTabButtonOpensNewTab(page, context, PROMETHEUS), WALKED_PROMETHEUS);
});

test("a tab whose IdP login got no response fails even while its URL still reads the IdP request", async () => {
  const { page, context } = dashboardWithTab(PROXIED, [[KEYCLOAK_FOR_PROXY, null]], [], KEYCLOAK_FOR_PROXY);
  await assert.rejects(assertTabButtonOpensNewTab(page, context, PROMETHEUS), WALKED_PROMETHEUS);
});

test("a tab that starts on an IdP login but lands off the IdP fails", async () => {
  const { page, context } = dashboardWithTab(PROXIED, [[KEYCLOAK_FOR_PROXY, 200]], [], DASHBOARD);
  await assert.rejects(assertTabButtonOpensNewTab(page, context, PROMETHEUS), WALKED_PROMETHEUS);
});

test("a tab that starts on an IdP login answering with a 5xx fails", async () => {
  const { page, context } = dashboardWithTab(PROXIED, [[KEYCLOAK_FOR_PROXY, 502]], [], KEYCLOAK_FOR_PROXY);
  await assert.rejects(assertTabButtonOpensNewTab(page, context, PROMETHEUS), WALKED_PROMETHEUS);
});

test("a front proxy that redirects the tab to a page its app answers passes", async () => {
  const { page, context } = dashboardWithTab(
    PIHOLE,
    [
      [PIHOLE, 302],
      [PIHOLE_ADMIN, 200],
    ],
    [],
    PIHOLE_ADMIN,
  );
  await assertTabButtonOpensNewTab(page, context, PIHOLE_TARGET);
});

test("a front proxy that redirects the tab to a page its dead app answers with a 5xx fails", async () => {
  const { page, context } = dashboardWithTab(
    PIHOLE,
    [
      [PIHOLE, 302],
      [PIHOLE_ADMIN, 502],
    ],
    [],
    PIHOLE_ADMIN,
  );
  await assert.rejects(assertTabButtonOpensNewTab(page, context, PIHOLE_TARGET), WALKED_PIHOLE);
});

test("a dead Element host that never answers the tab fails", async () => {
  const { page, context } = dashboardWithTab(ELEMENT, [[ELEMENT, null]], [], CHROME_ERROR);
  await assert.rejects(assertTabButtonOpensNewTab(page, context, MATRIX), WALKED_ELEMENT);
});

test("an Element host that answers the tab with a 5xx fails", async () => {
  const { page, context } = dashboardWithTab(ELEMENT, [[ELEMENT, 502]], [], ELEMENT);
  await assert.rejects(assertTabButtonOpensNewTab(page, context, MATRIX), WALKED_ELEMENT);
});

test("an Element host that redirects the tab away for good fails", async () => {
  const { page, context } = dashboardWithTab(
    ELEMENT,
    [
      [ELEMENT, 302],
      [DASHBOARD, 200],
    ],
    [],
    DASHBOARD,
  );
  await assert.rejects(assertTabButtonOpensNewTab(page, context, MATRIX), WALKED_ELEMENT);
});

test("the dashboard's own iframe answered by Element does not stand in for a tab that got no answer", async () => {
  const { page, context } = dashboardWithTab(ELEMENT, [[ELEMENT, null]], [[ELEMENT, 200]], CHROME_ERROR);
  await assert.rejects(assertTabButtonOpensNewTab(page, context, MATRIX), WALKED_ELEMENT);
});
