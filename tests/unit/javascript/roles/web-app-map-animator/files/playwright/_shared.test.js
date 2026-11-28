const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const APP = "http://animator.map.node.onion";
const ISSUER = "https://auth.example.test";
const APP_MATOMO = "http://matomo.node.onion";
const ISSUER_MATOMO = "https://matomo.example.test";
const AUTH_WALL = `${ISSUER}/realms/main/protocol/openid-connect/auth?client_id=web-app-map-animator`;
const LOGIN_FORM = `${APP}/renders/login?next=%2F`;
const identity = (value) => value;

process.env.APP_BASE_URL = APP;
process.env.CANONICAL_DOMAIN = new URL(APP).hostname;
process.env.MATOMO_BASE_URL = APP_MATOMO;

function expect(actual, message) {
  return {
    toBe: (expected) => assert.equal(actual, expected, message),
    toHaveURL: async (expected) => {
      const url = actual.url();
      assert.ok(typeof expected === "string" ? url === expected : expected.test(url), `${message} (received ${url})`);
    },
  };
}

const { assertCspInjections, installCspHeaderRecorder } = loadInternals(
  path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/csp.js"),
  ["assertCspInjections", "installCspHeaderRecorder"],
  {
    "@playwright/test": { expect },
    "../../timeouts": { resolveTimeout: identity },
  },
  { URL },
);

/**
 * Args:
 *   sso: whether the oauth2 gate sends an anonymous visit to the issuer first.
 *
 * Returns:
 *   The role's openApp and loginToApp, wired to the shared CSP recorder and assertion.
 */
function loadShared({ sso }) {
  return loadInternals(
    path.join(PROJECT_ROOT, "roles/web-app-map-animator/files/playwright/_shared.js"),
    ["openApp", "loginToApp"],
    {
      "@playwright/test": { expect },
      "./timeouts": { resolveTimeout: identity },
      "./personas": {
        decodeDotenvQuotedValue: identity,
        normalizeBaseUrl: identity,
        gotoOnion: async (page, url) => {
          installCspHeaderRecorder(page);
          page.visit(url);
        },
        safeIsEnabled: (name) => name === "matomo" || (name === "sso" && sso),
        performKeycloakLogin: async (page) => page.signInAtKeycloak(),
        assertCspInjections,
      },
    },
    {},
  );
}

/**
 * Args:
 *   sso: whether an anonymous visit lands on the issuer's login instead of the render server's.
 *   editorCsp: Content-Security-Policy the editor's onion vhost answers with.
 *
 * Returns:
 *   A Map Animator page reached over the onion whose SSO issuer keeps its one clearnet URL, so the
 *   issuer's login carries the clearnet Matomo host while the editor carries the onion one.
 */
function mapAnimator({ sso, editorCsp = `connect-src 'self' ${APP_MATOMO}` }) {
  const listeners = [];
  const mainFrame = {};
  const state = { url: "about:blank", signedIn: false };
  const land = (url) => {
    state.url = url;
    const csp = new URL(url).origin === ISSUER ? `connect-src 'self' ${ISSUER_MATOMO}` : editorCsp;
    const response = {
      frame: () => mainFrame,
      request: () => ({ resourceType: () => "document" }),
      headers: () => ({ "content-security-policy": csp }),
    };
    listeners.forEach((handler) => handler(response));
  };
  const form = {
    getByLabel: () => ({ fill: async () => {} }),
    getByRole: () => ({
      click: async () => {
        state.signedIn = true;
        land(`${APP}/`);
      },
    }),
  };
  return {
    url: () => state.url,
    mainFrame: () => mainFrame,
    on: (event, handler) => {
      if (event === "response") listeners.push(handler);
    },
    locator: () => form,
    waitForLoadState: async () => {},
    visit: (url) => land(url === `${APP}/` && !state.signedIn ? (sso ? AUTH_WALL : LOGIN_FORM) : url),
    signInAtKeycloak: () => land(LOGIN_FORM),
  };
}

test("an onion login through the clearnet issuer checks the editor's policy, not the issuer's", async () => {
  const page = mapAnimator({ sso: true });
  await loadShared({ sso: true }).loginToApp(page, "biber", "secret");
  assert.equal(page.url(), `${APP}/`);
});

test("an anonymous visit with SSO reads no policy off the issuer's login page", async () => {
  const page = mapAnimator({ sso: true });
  await loadShared({ sso: true }).openApp(page);
  assert.equal(page.url(), AUTH_WALL);
});

for (const sso of [true, false]) {
  test(`the editor's policy still fails the login when it misses an enabled injector (sso=${sso})`, async () => {
    const page = mapAnimator({ sso, editorCsp: "connect-src 'self'" });
    await assert.rejects(loadShared({ sso }).loginToApp(page, "biber", "secret"), /matomo\.node\.onion/);
    assert.equal(page.url(), `${APP}/`);
  });
}
