const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const { element, patch } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/logout-patch.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-pretix/files/playwright/test-rbac-teams.js");
const KEYCLOAK_LOGOUT_URL = "https://auth.example.org/realms/example.org/protocol/openid-connect/logout";
const NATIVE_LOGOUT_HREF = "/control/logout";
const HREF_SUFFIX_SELECTOR = /^a\[href\$='([^']+)'\]$/;

const { CONTROL_SESSION_MARKER } = loadInternals(
  SPEC,
  ["CONTROL_SESSION_MARKER"],
  {
    "@playwright/test": { test: Object.assign(() => undefined, { use: () => undefined }), expect: () => undefined },
    "./personas": {
      decodeDotenvQuotedValue: (value) => value,
      normalizeBaseUrl: (url) => url,
      requireDotenvValue: () => "https://ticket.example.org/",
    },
  },
  {},
);

/**
 * Returns:
 *   The logout and account links pretix's control navbar renders for a signed-in user, as the desktop layout shows them.
 */
function controlNavbar() {
  return {
    logout: element("A", { href: NATIVE_LOGOUT_HREF, title: "Log out" }, ""),
    account: element("A", { href: "/control/settings", title: "Account Settings" }, "Biber"),
  };
}

/**
 * Args:
 *   selector: an a[href$='...'] selector.
 *   elements: every element of the page.
 *
 * Returns:
 *   The anchors the selector matches.
 */
function matching(selector, elements) {
  const suffix = HREF_SUFFIX_SELECTOR.exec(selector);
  assert.ok(suffix, `the control session marker must stay an a[href$='...'] selector, got ${selector}`);
  return elements.filter((el) => el.tagName === "A" && (el.getAttribute("href") || "").endsWith(suffix[1]));
}

test("the control session marker finds the signed-in navbar after the universal logout patch rewrote its logout link", () => {
  const navbar = controlNavbar();
  patch([navbar.logout, navbar.account], KEYCLOAK_LOGOUT_URL);

  assert.deepEqual(matching(CONTROL_SESSION_MARKER, [navbar.logout, navbar.account]), [navbar.account]);
  assert.equal(navbar.account.dataset._logoutHandled, undefined);
});

test("without the universal logout the control session marker finds the same navbar link", () => {
  const navbar = controlNavbar();

  assert.deepEqual(matching(CONTROL_SESSION_MARKER, [navbar.logout, navbar.account]), [navbar.account]);
});

test("negative control: once the universal logout patch ran, the native logout href no longer exists to prove a session", () => {
  const navbar = controlNavbar();
  patch([navbar.logout, navbar.account], KEYCLOAK_LOGOUT_URL);

  assert.equal(navbar.logout.getAttribute("href"), KEYCLOAK_LOGOUT_URL);
  assert.deepEqual(matching(`a[href$='${NATIVE_LOGOUT_HREF}']`, [navbar.logout, navbar.account]), []);
});
