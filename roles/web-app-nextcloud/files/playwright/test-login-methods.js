const { test, expect } = require("@playwright/test");
const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const loginFormOffered =
  process.env.LOGIN_METHOD_NATIVE_ENABLED === "true" || process.env.LOGIN_METHOD_LDAP_ENABLED === "true";
const passkeyOffered = process.env.LOGIN_METHOD_PASSKEY_ENABLED === "true";

exports.register = function (shared) {
  test("login methods: with SSO on the sign-in page offers only the enabled entries", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    const keycloakAuth = `${normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"))}/protocol/openid-connect/auth`;
    await gotoOnion(page, new URL("login", shared.env.nextcloudBaseUrl).toString());
    if (page.url().includes(keycloakAuth)) {
      expect(
        loginFormOffered || passkeyOffered,
        "oidc_login_auto_redirect hands /login to Keycloak only while SSO is the single sign-in entry",
      ).toBe(false);
      return;
    }
    await expect(
      page.locator("#alternative-logins a, #alternative-logins button").first(),
      "expected the SSO entry on the Nextcloud sign-in page",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
    await expect(page.getByRole("textbox", { name: shared.env.nextcloudUsernameFieldPattern })).toHaveCount(loginFormOffered ? 1 : 0);
    await expect(page.getByRole("button", { name: /log in with a device/i })).toHaveCount(passkeyOffered ? 1 : 0);
  });

  test("login methods: the local administrator signs in through /login?noredir=1&direct=1 with SSO on", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    await gotoOnion(page, new URL("login?noredir=1&direct=1", shared.env.nextcloudBaseUrl).toString());
    const usernameField = page.getByRole("textbox", { name: shared.env.nextcloudUsernameFieldPattern });
    await expect(usernameField, "expected the break-glass form that ?direct=1 shows despite hide_login_form").toBeVisible({
      timeout: resolveTimeout(60_000),
    });
    await usernameField.fill(shared.env.loginUsername);
    await page.locator('input[name="password"], input[type="password"]').first().fill(shared.env.loginPassword);
    await page.getByRole("button", { name: shared.env.nextcloudCredentialSubmitPattern }).click({ timeout: resolveTimeout(30_000) });
    const shellState = await shared.waitForVisibleCandidate(
      page,
      shared.getNextcloudShellCandidates(page),
      resolveTimeout(120_000),
      "Timed out waiting for a signed-in Nextcloud shell after the break-glass login",
    );
    await expect(shellState.locator).toBeVisible();
  });
};
