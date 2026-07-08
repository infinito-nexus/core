const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

// Administrator native login — picks the variant-specific path at runtime.
// Skips entirely when neither oauth2 nor ldap is enabled (v1 has no auth
// providers wired, the role only serves the public landing).

exports.register = function (shared) {
  test("friendica: administrator native login and logout", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");

    if (shared.isServiceEnabled("sso")) {
      // v0: full double-login via oauth2-proxy + Keycloak round-trip.
      await shared.loginViaOauth2ProxyAndFriendica(page, shared.env.adminUsername, shared.env.adminPassword);
    } else {
      // v2: direct /login form, no Keycloak step.
      await shared.loginViaFriendicaDirect(page, shared.env.adminUsername, shared.env.adminPassword);
    }

    await shared.friendicaLogout(page);
    await gotoOnion(page, `${shared.trimmedBaseUrl()}/network`, { waitUntil: "domcontentloaded" }).catch(() => {});
    await expect(page.locator("a[href*='/logout']")).not.toBeAttached({ timeout: resolveTimeout(10_000) });
  });
};
