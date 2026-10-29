const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { runGuestFlow, safeIsEnabled, performKeycloakLoginExpectingDenial } = require("./personas");

exports.register = function (shared) {
  test("guest: front page → login → never authenticated", async ({ page }) => {
    await runGuestFlow(page);
  });

  test("guest: front page → login without an account is rejected", async ({ page }) => {
    test.setTimeout(resolveTimeout(120_000)); // Keycloak round-trip of the oauth2 gate
    await shared.openApp(page);

    if (safeIsEnabled("sso")) {
      await performKeycloakLoginExpectingDenial(page, "", "", shared.env.canonicalDomain);
      await shared.openApp(page);
    } else {
      await shared.nativeLogin(page, "guest-without-account", "not-a-password");
      await expect(page, "a rejected login must stay on the login form").toHaveURL(/\/renders\/login\?failed=1/, {
        timeout: resolveTimeout(30_000),
      });
      await expect(page.getByRole("alert")).toHaveText("Wrong user or password.");
    }
    await expect(page.getByRole("button", { name: "Log out" })).toHaveCount(0);
  });
};
