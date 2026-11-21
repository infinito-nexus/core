const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-decidim/files/playwright/test-seaweedfs.js");
const ADMIN_EMAIL = "administrator@example.org";
const ADMIN_PASSWORD = "secret";
const ADMIN_LOGIN_ID = "administrator";

Object.assign(process.env, {
  DECIDIM_BASE_URL: "https://decidim.example.org",
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
});

class SignedIn extends Error {}

/**
 * Args:
 *   loginMethodNative: the LOGIN_METHOD_NATIVE_ENABLED flag _shared.js reads.
 *
 * Returns:
 *   The spec's test body, run up to the signed-in check, and the Keycloak sign-ins it asked _shared.js for.
 */
function loadSpec(loginMethodNative) {
  const bodies = [];
  const signIns = [];
  const playwrightTest = Object.assign((title, body) => bodies.push(body), {
    setTimeout: () => undefined,
    skip: () => undefined,
    use: () => undefined,
  });
  const expect = () => ({
    toBeTruthy: () => undefined,
    not: {
      toHaveURL: async () => {
        throw new SignedIn();
      },
    },
  });
  loadInternals(
    SPEC,
    [],
    {
      "@playwright/test": { expect, test: playwrightTest },
      "./timeouts": { isOnionTarget: () => false, resolveTimeout: (ms) => ms },
      "./personas": {
        decodeDotenvQuotedValue: (value) => value,
        runSeaweedfsStorageCheck: async (page, browser, { action }) => action(page),
      },
      "./_shared": {
        adminKeycloakLoginId: () => ADMIN_LOGIN_ID,
        env: { loginMethodNative },
        oidcLogin: async (page, username, password) => {
          signIns.push({ page, username, password });
        },
      },
    },
    { Buffer },
  );
  return { run: (page) => bodies[0]({ page, browser: {} }), signIns };
}

/**
 * Args:
 *   emailField: whether the sign-in page renders Decidim's e-mail form.
 *
 * Returns:
 *   A page stand-in and the values typed into it.
 */
function signInPage(emailField) {
  const typed = [];
  const field = {
    first: () => field,
    isVisible: async () => false,
    waitFor: async () => {
      if (!emailField) throw new Error("locator.waitFor: Timeout exceeded, the sign-in page offers SSO only");
    },
    fill: async (value) => {
      typed.push(value);
    },
    click: async () => undefined,
  };
  const page = {
    goto: async () => null,
    waitForLoadState: async () => undefined,
    getByLabel: () => field,
    getByRole: () => field,
    locator: () => field,
  };
  return { page, typed };
}

test("with native sign-in off the administrator signs in through Keycloak instead of waiting for an e-mail field", async () => {
  const { run, signIns } = loadSpec(false);
  const { page, typed } = signInPage(false);
  await assert.rejects(run(page), SignedIn);
  assert.deepEqual(signIns, [{ page, username: ADMIN_LOGIN_ID, password: ADMIN_PASSWORD }]);
  assert.deepEqual(typed, []);
});

test("with native sign-in on the administrator signs in through Decidim's e-mail form", async () => {
  const { run, signIns } = loadSpec(true);
  const { page, typed } = signInPage(true);
  await assert.rejects(run(page), SignedIn);
  assert.deepEqual(signIns, []);
  assert.deepEqual(typed, [ADMIN_EMAIL, ADMIN_PASSWORD]);
});
