const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const BASE = "https://forum.example.org";
const ISSUER = "https://auth.example.org/realms/main";
const CHECK_MS = 50;
const WAIT_MS = 500;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Args:
 *   subject: a fake locator.
 *   message: the failure message.
 *
 * Returns:
 *   The matchers sign-in.js uses, each retried until it holds or its timeout passes, as Playwright's web-first assertions are.
 */
function pollingExpect(subject, message) {
  const until = async (holds, { timeout }) => {
    const deadline = Date.now() + timeout;
    while (!(await holds())) {
      if (Date.now() >= deadline) {
        throw new Error(message);
      }
      await sleep(5);
    }
  };
  return {
    toBeVisible: (options) => until(() => subject.isVisible(), options),
    toBeEnabled: (options) => until(() => subject.isEnabled(), options),
    toHaveClass: (pattern, options) => until(async () => pattern.test(await subject.getAttribute("class")), options),
  };
}
pollingExpect.poll = (read, { message }) => ({
  toContain: async (expected) => assert.ok(read().includes(expected), message),
});

/**
 * Args:
 *   existingAccount: whether Discourse already holds an account for the persona and opens the session straight away.
 *   usernameAvailable: what the availability check of the IdP-filled username answers once it settles.
 *
 * Returns:
 *   The page, the Keycloak login that lands on it and its state. A first login renders the account form with the
 *   username tip at `tip bad` ("Checking username availability…") for CHECK_MS; Sign Up opens the session only
 *   while the tip reads `tip good` and otherwise leaves the form standing, as Discourse v2026.10.2 did in the
 *   trace of CI run 45313925049. `clicks` records the tip each Sign Up click met.
 */
function discoursePage({ existingAccount, usernameAvailable }) {
  const state = { url: "about:blank", form: false, tip: "tip bad", session: false, clicks: [] };
  const userMenu = { isVisible: async () => state.session };
  const signUp = {
    isVisible: async () => state.form && !state.session,
    isEnabled: async () => true,
    click: async () => {
      state.clicks.push(state.tip);
      state.session = state.tip === "tip good";
    },
  };
  userMenu.or = (other) => ({
    first: () => ({ isVisible: async () => (await userMenu.isVisible()) || (await other.isVisible()) }),
  });
  const locators = {
    "a, button": {
      filter: () => ({
        first: () => ({
          click: async () => {
            state.url = `${ISSUER}/protocol/openid-connect/auth`;
          },
        }),
      }),
    },
    ".header-dropdown-toggle.current-user": userMenu,
    ".signup-page-cta__signup": signUp,
    "#username-validation": { getAttribute: async () => state.tip },
  };
  const login = async () => {
    state.url = `${BASE}/`;
    state.session = existingAccount;
    state.form = !existingAccount;
    setTimeout(() => {
      state.tip = usernameAvailable ? "tip good" : "tip bad";
    }, CHECK_MS);
  };
  return { page: { url: () => state.url, locator: (selector) => locators[selector] }, login, state };
}

function loadSignInAs(login) {
  return loadInternals(
    path.join(PROJECT_ROOT, "roles/web-app-discourse/files/playwright/sign-in.js"),
    ["signInAs"],
    {
      "@playwright/test": { expect: pollingExpect },
      "./personas": {
        decodeDotenvQuotedValue: () => BASE,
        gotoOnion: async () => {},
        normalizeBaseUrl: (value) => value,
        performKeycloakLoginForm: login,
        requireDotenvValue: () => ISSUER,
      },
      "./service-gating": { isServiceEnabled: (service) => service === "sso" },
      "./timeouts": { resolveTimeout: () => WAIT_MS },
    },
    {},
  ).signInAs;
}

test("a first OIDC login sends the account form only once Discourse confirmed the username, and opens the session", async () => {
  const { page, login, state } = discoursePage({ existingAccount: false, usernameAvailable: true });

  await loadSignInAs(login)(page, "biber", "secret");

  assert.deepEqual(state.clicks, ["tip good"]);
  assert.equal(state.session, true);
});

test("a username Discourse does not confirm fails the first login without sending the account form", async () => {
  const { page, login, state } = discoursePage({ existingAccount: false, usernameAvailable: false });

  await assert.rejects(loadSignInAs(login)(page, "biber", "secret"), /confirm the IdP-filled username as available/);

  assert.deepEqual(state.clicks, []);
});

test("a returning account opens the session without touching the account form", async () => {
  const { page, login, state } = discoursePage({ existingAccount: true, usernameAvailable: false });

  await loadSignInAs(login)(page, "administrator", "secret");

  assert.deepEqual(state.clicks, []);
  assert.equal(state.session, true);
});
