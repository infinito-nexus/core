const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const LAM_JS = path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/lam.js");
const LAM = "https://lam.example.test";
const LAM_LOGIN = `${LAM}/lam/templates/login.php`;
const KEYCLOAK_AUTH = "https://auth.example.test/realms/main/protocol/openid-connect/auth";
const USERNAME = "administrator";
const PASSWORD = "probe-secret";
const SUBMIT = 'button[name="checklogin"]';
const SIGNED_IN = '#lam-topnav a.lam-menu-entry[href$="/templates/lists/list.php?type=user"]';

/**
 * Args:
 *   ssoGate: whether LAM's login page first bounces to Keycloak until the Keycloak form is passed.
 *
 * Returns:
 *   A page double that records every navigation, fill, click and assertion in `events`.
 */
function fakePage(ssoGate) {
  const events = [];
  let url = "about:blank";
  let gatePassed = !ssoGate;
  return {
    events,
    land(target) {
      url = target === LAM_LOGIN && !gatePassed ? KEYCLOAK_AUTH : target;
    },
    passGate() {
      gatePassed = true;
      url = LAM_LOGIN;
    },
    url: () => url,
    locator: (selector) => ({
      selector,
      events,
      fill: async (value) => events.push(["fill", selector, value]),
      click: async () => events.push(["click", selector]),
    }),
    waitForURL: async (predicate) => {
      assert.equal(predicate(new URL(url)), true, "the wait must end once the SSO hop is left");
    },
    waitForLoadState: async () => {},
  };
}

const { signInToLam } = loadInternals(
  LAM_JS,
  ["signInToLam"],
  {
    "@playwright/test": {
      expect: (target) => ({
        toBeEditable: async () => target.events.push(["editable", target.selector]),
        toHaveCount: async (count) => target.events.push(["count", target.selector, count]),
      }),
    },
    "../../timeouts": { resolveTimeout: (ms) => ms },
    "./onion": {
      gotoOnion: async (page, target) => {
        page.events.push(["goto", target]);
        page.land(target);
      },
    },
    "./keycloak": {
      performKeycloakLoginForm: async (page, username, password) => {
        page.events.push(["keycloak", username, password]);
        page.passGate();
      },
    },
  },
  { URL },
);

const actions = (events) => events.filter(([kind]) => ["goto", "keycloak", "fill", "click"].includes(kind));

test("LAM's search login gets the user name and the password before the submit and lands on the account list", async () => {
  const page = fakePage(false);

  await signInToLam(page, LAM, USERNAME, PASSWORD);

  assert.deepEqual(actions(page.events), [
    ["goto", LAM_LOGIN],
    ["fill", "input#username", USERNAME],
    ["fill", "input#passwd", PASSWORD],
    ["click", SUBMIT],
  ]);
  assert.deepEqual(page.events.at(-1), ["count", SIGNED_IN, 1]);
});

test("behind the oauth2-proxy gate Keycloak takes the credentials before LAM's own form is filled", async () => {
  const page = fakePage(true);

  await signInToLam(page, LAM, USERNAME, PASSWORD);

  assert.deepEqual(actions(page.events), [
    ["goto", LAM_LOGIN],
    ["keycloak", USERNAME, PASSWORD],
    ["goto", LAM_LOGIN],
    ["fill", "input#username", USERNAME],
    ["fill", "input#passwd", PASSWORD],
    ["click", SUBMIT],
  ]);
});

test("a base URL with a trailing slash still opens LAM's login page", async () => {
  const page = fakePage(false);

  await signInToLam(page, `${LAM}/`, USERNAME, PASSWORD);

  assert.deepEqual(page.events[0], ["goto", LAM_LOGIN]);
});
