const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const BASE = "https://decidim.example.org";
const identity = (value) => value;

const { adminAreaAccess } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-decidim/files/playwright/test-rbac.js"),
  ["adminAreaAccess"],
  {
    "./timeouts": { resolveTimeout: identity },
    "./personas": {
      decodeDotenvQuotedValue: identity,
      gotoOnion: (page, url, opts) => page.goto(url, opts),
      normalizeBaseUrl: identity,
      requireDotenvValue: identity,
    },
  },
  { URL },
);

/**
 * Args:
 *   finalPath: path the navigation to /admin/ ends on.
 *   status: HTTP status of the response the navigation ends with.
 *
 * Returns:
 *   A page stand-in whose goto resolves like Playwright's, with the response after the last redirect.
 */
function landingOn(finalPath, status) {
  return {
    goto: async () => ({ ok: () => status >= 200 && status < 300, status: () => status }),
    url: () => `${BASE}${finalPath}`,
    waitForLoadState: async () => undefined,
  };
}

test("the user_manager role opens the administration, also through the admin terms redirect", async () => {
  assert.equal(await adminAreaAccess(landingOn("/admin/admin_terms/show", 200), BASE), "granted");
  assert.equal(await adminAreaAccess(landingOn("/admin/", 200), BASE), "granted");
});

test("the 404 Decidim renders in place at /admin for a user without an admin role refuses the administration", async () => {
  assert.equal(await adminAreaAccess(landingOn("/admin", 404), BASE), "refused");
});

test("a lost session or an error page proves neither a grant nor a refusal", async () => {
  assert.equal(await adminAreaAccess(landingOn("/users/sign_in", 200), BASE), "HTTP 200 at /users/sign_in");
  assert.equal(await adminAreaAccess(landingOn("/admin", 502), BASE), "HTTP 502 at /admin");
  assert.equal(await adminAreaAccess(landingOn("/admin", 403), BASE), "HTTP 403 at /admin");
});
