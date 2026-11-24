const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const { DOMAIN } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/domain.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-dashboard/files/playwright/test-tile-reachability.js");
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
const BRIDGY = `https://bridgyfed.${DOMAIN}/`;
const JENKINS = `https://jenkins.${DOMAIN}/`;
const JENKINS_LOGIN = `${JENKINS}securityRealm/commenceLogin?from=%2F`;
const KEYCLOAK_FOR_JENKINS = `${KEYCLOAK_AUTH}?response_type=code&client_id=jenkins&redirect_uri=${encodeURIComponent(`${JENKINS}securityRealm/finishLogin`)}`;
const DEFAULT_OK = [200, 302, 301];
const MATRIX = {
  id: "web-app-matrix",
  canonical_domain: `element.${DOMAIN}`,
  handover_domain: "",
  domains: [`element.${DOMAIN}`, `jitsi.matrix.${DOMAIN}`, `matrix.${DOMAIN}`],
  status_codes: DEFAULT_OK,
};
const MATRIX_WITHOUT_HOMESERVER = { ...MATRIX, domains: [`element.${DOMAIN}`, `jitsi.matrix.${DOMAIN}`] };
const PROMETHEUS = {
  id: "web-app-prometheus",
  canonical_domain: `prometheus.${DOMAIN}`,
  handover_domain: "",
  domains: [`prometheus.${DOMAIN}`],
  status_codes: DEFAULT_OK,
};
const PIHOLE_TARGET = {
  id: "web-app-pihole",
  canonical_domain: `pihole.${DOMAIN}`,
  handover_domain: "",
  domains: [`pihole.${DOMAIN}`],
  status_codes: DEFAULT_OK,
};
const BRIDGY_TARGET = {
  id: "web-app-bridgy-fed",
  canonical_domain: `bridgyfed.${DOMAIN}`,
  handover_domain: "",
  domains: [`bridgyfed.${DOMAIN}`],
  status_codes: [...DEFAULT_OK, 404],
};
const JENKINS_TARGET = {
  id: "web-app-jenkins",
  canonical_domain: `jenkins.${DOMAIN}`,
  handover_domain: "",
  domains: [`jenkins.${DOMAIN}`],
  status_codes: [...DEFAULT_OK, 403],
};
const ESCAPED_DOMAIN = DOMAIN.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const WALKED_ELEMENT = new RegExp(`Expected the embedded element\\.${ESCAPED_DOMAIN} to answer the new tab`);
const WALKED_PIHOLE = new RegExp(`Expected the embedded pihole\\.${ESCAPED_DOMAIN} to answer the new tab`);
const WALKED_PROMETHEUS = new RegExp(`Expected the embedded prometheus\\.${ESCAPED_DOMAIN} to answer the new tab`);
const WALKED_BRIDGY = new RegExp(`Expected the embedded bridgyfed\\.${ESCAPED_DOMAIN} to answer the new tab`);
const WALKED_JENKINS = new RegExp(
  `Expected the embedded jenkins\\.${ESCAPED_DOMAIN} to answer the new tab, it navigated .*commenceLogin\\S* \\(no response\\)`,
);
const browserSteps = [];

/**
 * Args:
 *   actual: the value under assertion, or the block toPass retries.
 *   message: the failure message.
 *
 * Returns:
 *   The matchers assertTabButtonOpensNewTab calls, failing like Playwright's with the message. toPass runs its block,
 *   lets the browser take the next of browserSteps after each failure, as Playwright's polling gives a tab that keeps
 *   navigating, and rethrows the last failure once no step is left.
 */
function expect(actual, message) {
  return {
    toBeVisible: async () => {},
    toBe: (expected) => assert.equal(actual, expected, message),
    toPass: async () => {
      for (;;) {
        try {
          return await actual();
        } catch (error) {
          const step = browserSteps.shift();
          if (!step) {
            throw error;
          }
          step();
        }
      }
    },
  };
}

/**
 * Args:
 *   file: the spec file to load.
 *
 * Returns:
 *   Its assertTabButtonOpensNewTab.
 */
function loadAssertion(file) {
  return loadInternals(
    file,
    ["assertTabButtonOpensNewTab"],
    {
      "./fixtures/onion-test": { test: () => {}, expect },
      "./timeouts": { resolveTimeout: (ms) => ms },
      "./personas": { decodeDotenvJsonList: () => [], gotoOnion: async () => {} },
    },
    { URL },
  ).assertTabButtonOpensNewTab;
}

const assertTabButtonOpensNewTab = loadAssertion(SPEC);

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
 *   { page, context, listeners, tab }: a dashboard whose Tab button opens a tab that walks tabHops. tab drives that tab
 *   on after its document loaded: tab.answer(url, status) answers its request for url, tab.walk([url, status]) sends a
 *   further navigation, and tab.land(url) moves the URL it shows.
 */
function dashboardWithTab(embedded, tabHops, embedHops, landing) {
  const listeners = { request: new Set(), response: new Set() };
  let announce;
  const announced = new Promise((resolve) => {
    announce = resolve;
  });
  let shown = landing;
  const page = {};
  const popup = { url: () => shown, waitForLoadState: async () => {}, close: async () => {} };
  const popupFrame = { page: () => popup, parentFrame: () => null };
  const embedFrame = { page: () => page, parentFrame: () => ({}) };
  const tabRequests = new Map();
  const answer = (request, status) =>
    listeners.response.forEach((listener) => listener({ request: () => request, status: () => status }));
  const walk = ([url, status], frame) => {
    const request = navigation(url, frame);
    listeners.request.forEach((listener) => listener(request));
    if (status !== null) {
      answer(request, status);
    }
    return request;
  };
  const tabButton = {
    isVisible: async () => true,
    click: async () => {
      embedHops.forEach((hop) => walk(hop, embedFrame));
      tabHops.forEach((hop, index) => tabRequests.set(hop[0], walk(hop, index === 0 ? null : popupFrame)));
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
  const tab = {
    answer: (url, status) => answer(tabRequests.get(url), status),
    walk: (hop) => tabRequests.set(hop[0], walk(hop, popupFrame)),
    land: (url) => {
      shown = url;
    },
  };
  return { page, context, listeners, tab };
}

/**
 * Args:
 *   tab: the tab controls dashboardWithTab returns.
 *
 * Returns:
 *   Nothing; queues the browser step in which Jenkins answers the login redirect its 403 page scripted with a 302 to
 *   the IdP, and the tab lands on that IdP login.
 */
function jenkinsLoginAnswersLater(tab) {
  browserSteps.push(() => {
    tab.answer(JENKINS_LOGIN, 302);
    tab.walk([KEYCLOAK_FOR_JENKINS, 200]);
    tab.land(KEYCLOAK_FOR_JENKINS);
  });
}

/**
 * Returns:
 *   The path of a planted copy of the spec that judges the tab once, as soon as its first document loaded, for a
 *   negative control.
 */
function judgedOnce() {
  const source = [
    ["await expect(() => {", "await (() => {"],
    ["}).toPass({ timeout: resolveTimeout(30_000) });", "})();"],
  ].reduce((text, [old, replacement]) => {
    assert.equal(text.split(old).length, 2, `the plant ${old} must occur exactly once`);
    return text.replace(old, replacement);
  }, fs.readFileSync(SPEC, "utf8"));
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "tile-reachability-plant-"));
  const file = path.join(directory, "test-tile-reachability.js");
  fs.writeFileSync(file, source);
  return file;
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

test("a tab that starts on an IdP login returning to the role's Synapse homeserver passes", async () => {
  const { page, context } = dashboardWithTab(ELEMENT, [[KEYCLOAK_FOR_SYNAPSE, 200]], [], KEYCLOAK_FOR_SYNAPSE);
  await assertTabButtonOpensNewTab(page, context, MATRIX);
});

test("a tab that starts on an IdP login returning to a homeserver outside the role's domains fails", async () => {
  const { page, context } = dashboardWithTab(ELEMENT, [[KEYCLOAK_FOR_SYNAPSE, 200]], [], KEYCLOAK_FOR_SYNAPSE);
  await assert.rejects(assertTabButtonOpensNewTab(page, context, MATRIX_WITHOUT_HOMESERVER), WALKED_ELEMENT);
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

test("a federation host whose root answers the 404 its role declares passes", async () => {
  const { page, context } = dashboardWithTab(BRIDGY, [[BRIDGY, 404]], [], BRIDGY);
  await assertTabButtonOpensNewTab(page, context, BRIDGY_TARGET);
});

test("an Element host that answers the tab with a 404 its role does not declare fails", async () => {
  const { page, context } = dashboardWithTab(ELEMENT, [[ELEMENT, 404]], [], ELEMENT);
  await assert.rejects(assertTabButtonOpensNewTab(page, context, MATRIX), WALKED_ELEMENT);
});

test("a declared 404 does not excuse a federation host that answers with a 5xx", async () => {
  const { page, context } = dashboardWithTab(BRIDGY, [[BRIDGY, 502]], [], BRIDGY);
  await assert.rejects(assertTabButtonOpensNewTab(page, context, BRIDGY_TARGET), WALKED_BRIDGY);
});

test("a Jenkins tab whose 403 page scripts the login redirect passes once that redirect hands off to the IdP", async () => {
  const { page, context, tab } = dashboardWithTab(
    JENKINS,
    [
      [JENKINS, 403],
      [JENKINS_LOGIN, null],
    ],
    [],
    JENKINS,
  );
  jenkinsLoginAnswersLater(tab);
  try {
    await assertTabButtonOpensNewTab(page, context, JENKINS_TARGET);
    assert.equal(browserSteps.length, 0, "the verdict must wait for the login redirect still in flight when the tab's first document loaded");
  } finally {
    browserSteps.length = 0;
  }
});

test("a Jenkins tab whose scripted login redirect never answers fails", async () => {
  const { page, context } = dashboardWithTab(
    JENKINS,
    [
      [JENKINS, 403],
      [JENKINS_LOGIN, null],
    ],
    [],
    JENKINS,
  );
  await assert.rejects(assertTabButtonOpensNewTab(page, context, JENKINS_TARGET), WALKED_JENKINS);
});

test("negative control: judging the Jenkins tab at its first document fails though its login redirect answers later", async () => {
  const file = judgedOnce();
  const { page, context, tab } = dashboardWithTab(
    JENKINS,
    [
      [JENKINS, 403],
      [JENKINS_LOGIN, null],
    ],
    [],
    JENKINS,
  );
  jenkinsLoginAnswersLater(tab);
  try {
    await assert.rejects(loadAssertion(file)(page, context, JENKINS_TARGET), WALKED_JENKINS);
  } finally {
    browserSteps.length = 0;
    fs.rmSync(path.dirname(file), { recursive: true, force: true });
  }
});
