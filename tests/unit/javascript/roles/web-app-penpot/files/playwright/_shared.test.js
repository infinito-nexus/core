const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const BASE = "https://penpot.example.test";
const ISSUER = "https://auth.example.test/realms/main";
const DASHBOARD = `${BASE}/?screen=dashboard-recent&team-id=7b12b6b6`;
const SIDEBAR = "[data-testid='dashboard-sidebar']";

function pollMatchers(read, message, negate) {
  return {
    toMatch: async (pattern) => {
      const value = await read();
      assert.equal(pattern.test(value), !negate, `${message} (received ${value})`);
    },
    toContain: async (part) => {
      const value = await read();
      assert.equal(value.includes(part), !negate, `${message} (received ${value})`);
    },
  };
}

function expect(locator, message) {
  return {
    toBeVisible: async () => assert.ok(await locator.isVisible(), message),
    toBeEnabled: async () => assert.ok(await locator.isEnabled(), message),
  };
}
expect.poll = (read, { message }) => ({ ...pollMatchers(read, message, false), not: pollMatchers(read, message, true) });

const registers = new Proxy(() => undefined, { get: () => () => undefined });

process.env.PENPOT_BASE_URL = BASE;
process.env.OIDC_ISSUER_URL = ISSUER;

const { assertAuthenticated, penpotOidcLogin, loginRoute, screenOf } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-penpot/files/playwright/_shared.js"),
  ["assertAuthenticated", "penpotOidcLogin", "loginRoute", "screenOf"],
  {
    "@playwright/test": { expect, test: registers },
    "./timeouts": { resolveTimeout: (ms) => ms },
    "./personas": {
      decodeDotenvQuotedValue: (value) => value,
      normalizeBaseUrl: (value) => value,
      gotoOnion: async (page, url) => page.goto(url),
      performKeycloakLoginForm: async (page) => page.signedInAtKeycloak(),
    },
  },
  { URL },
);

/**
 * Args:
 *   callback: screen Penpot 2.19 answers the OIDC callback with; "register" stands for a first sign-in.
 *   fullname: full name the identity provider handed to the first sign-in form.
 *
 * Returns:
 *   The fake Penpot page and its state: the current URL, the full name in the form and the profiles created.
 */
function penpot({ callback, fullname = "" }) {
  const state = { url: "about:blank", fullname, created: 0 };
  const screen = () => new URL(state.url).searchParams.get("screen") || "";
  const control = (visible, actions = {}) => ({
    isVisible: async () => visible(),
    isEnabled: async () => visible(),
    ...actions,
  });
  const hidden = control(() => false);
  const page = {
    url: () => state.url,
    goto(url) {
      const legacy = /^#\/(.*)$/.exec(new URL(url).hash);
      state.url = legacy ? `${BASE}/?screen=${legacy[1].replace(/\//g, "-")}` : url;
    },
    signedInAtKeycloak() {
      state.url = callback === "register" ? `${BASE}/?screen=auth-register-validate&token=prepared` : callback;
    },
    getByText: (text) =>
      text === "OpenID"
        ? control(() => screen() === "auth-login", {
            click: async () => {
              state.url = `${ISSUER}/protocol/openid-connect/auth?client_id=penpot`;
            },
          })
        : hidden,
    getByLabel: (pattern) =>
      pattern.test("Full Name")
        ? control(() => screen() === "auth-register-validate", {
            inputValue: async () => state.fullname,
            fill: async (value) => {
              state.fullname = value;
            },
          })
        : hidden,
    getByRole: (role, { name }) =>
      role === "button" && name.test("Create an account")
        ? control(() => screen() === "auth-register-validate" && state.fullname !== "", {
            click: async () => {
              state.created += 1;
              state.url = DASHBOARD;
            },
          })
        : hidden,
    locator: (selector) => control(() => selector === SIDEBAR && screen().startsWith("dashboard-")),
  };
  return { page, state };
}

test("the login route uses the query-string screen Penpot 2.19 routes by", () => {
  assert.equal(loginRoute(`${BASE}/`), `${BASE}/?screen=auth-login`);
});

test("the editor screen is read from the screen key Penpot 2.19 puts in the query string", () => {
  assert.equal(screenOf(`${BASE}/?screen=workspace&team-id=7b12b6b6&file-id=1f2e`), "workspace");
  assert.equal(screenOf(`${BASE}/#/workspace?team-id=7b12b6b6`), "");
});

test("an existing profile signs in via OIDC straight to the query-routed dashboard", async () => {
  const { page, state } = penpot({ callback: DASHBOARD });
  await penpotOidcLogin(page, "administrator", "secret");
  assert.equal(state.url, DASHBOARD);
  assert.equal(state.created, 0);
});

test("a first OIDC sign-in submits Penpot's registration form and lands on the dashboard", async () => {
  const { page, state } = penpot({ callback: "register" });
  await penpotOidcLogin(page, "biber", "secret");
  assert.equal(state.created, 1);
  assert.equal(state.fullname, "biber");
  assert.equal(state.url, DASHBOARD);
});

test("a full name the identity provider handed over is kept on the first sign-in", async () => {
  const { page, state } = penpot({ callback: "register", fullname: "Platform Administrator" });
  await penpotOidcLogin(page, "administrator", "secret");
  assert.equal(state.created, 1);
  assert.equal(state.fullname, "Platform Administrator");
});

test("an OIDC callback that ends on the login screen fails instead of waiting for a form", async () => {
  const { page, state } = penpot({ callback: `${BASE}/?screen=auth-login&error=registration-disabled` });
  await assert.rejects(penpotOidcLogin(page, "biber", "secret"), /dashboard or its first sign-in form/);
  assert.equal(state.created, 0);
});

test("an auth screen never counts as signed in", async () => {
  for (const url of [`${BASE}/?screen=auth-login`, `${BASE}/?screen=auth-register-validate&token=t`, `${BASE}/#/dashboard/recent`]) {
    const { page, state } = penpot({ callback: DASHBOARD });
    state.url = url;
    await assert.rejects(assertAuthenticated(page), /dashboard screen after sign-in/, url);
  }
});
