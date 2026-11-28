const crypto = require("crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessAddonEnabled } = require("./addon-gating");
const { skipUnlessServiceDisabled } = require("./service-gating");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const nativeEnabled = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const adminPassword = decodeDotenvQuotedValue(process.env.NEXTCLOUD_DIRECT_LOGIN_PASSWORD || "");
const SHELL = "#app-content-vue, #app-navigation-vue, #app-dashboard, nav.app-menu, #user-menu";

/**
 * Args:
 *   request: the Playwright request fixture.
 *   method: the HTTP method.
 *   url: the absolute endpoint URL.
 *   options: headers, form or data of the call.
 *
 * Returns:
 *   The APIResponse.
 */
function call(request, method, url, options = {}) {
  return request.fetch(url, { method, ...options, timeout: resolveTimeout(30_000) });
}

/**
 * Args:
 *   response: an OCS v2 APIResponse.
 *   action: the provisioning step, named in the failure message.
 */
async function expectOcsSuccess(response, action) {
  expect(response.status(), `${action} must answer HTTP 200`).toBe(200);
  expect((await response.json()).ocs.meta.statuscode, `${action} must report OCS status 200`).toBe(200);
}

exports.register = function (shared) {
  test("2fa enrollment: with its own second factor enforced Nextcloud sends a local account without one to setup before it gets in", async ({ page, request }) => {
    skipUnlessServiceDisabled("sso");
    skipUnlessAddonEnabled("twofactor_totp");
    test.skip(!nativeEnabled, "LOGIN_METHOD_NATIVE_ENABLED=false");
    test.setTimeout(resolveTimeout(240_000));
    expect(adminPassword, "NEXTCLOUD_DIRECT_LOGIN_PASSWORD must be set").toBeTruthy();

    const base = shared.env.nextcloudBaseUrl;
    const admin = {
      Authorization: `Basic ${Buffer.from(`${shared.env.loginUsername}:${adminPassword}`).toString("base64")}`,
      "OCS-APIRequest": "true",
      Accept: "application/json",
    };
    const suffix = `${Date.now().toString(36)}${crypto.randomBytes(3).toString("hex")}`;
    const group = `infinito-2fa-probe-${suffix}`;
    const probe = { username: `infinito-2fa-probe-${suffix}`, password: crypto.randomBytes(24).toString("base64url") };
    const enforcementUrl = new URL("index.php/settings/api/admin/twofactorauth", base).toString();
    const ocs = (path) => new URL(`ocs/v2.php/cloud/${path}`, base).toString();

    const current = await call(request, "GET", enforcementUrl, { headers: admin });
    expect(current.status(), "the administrator must read the two-factor enforcement state").toBe(200);
    const previous = await current.json();
    let enforcing = false;
    try {
      await expectOcsSuccess(await call(request, "POST", ocs("groups"), { headers: admin, form: { groupid: group } }), "creating the probe group");
      await expectOcsSuccess(
        await call(request, "POST", ocs("users"), {
          headers: admin,
          form: { userid: probe.username, password: probe.password, "groups[]": group },
        }),
        "creating the probe account",
      );
      const enforce = await call(request, "PUT", enforcementUrl, {
        headers: admin,
        data: { enforced: true, enforcedGroups: [group], excludedGroups: [] },
      });
      expect(enforce.status(), "the administrator must enforce the second factor for the probe group").toBe(200);
      enforcing = true;

      await gotoOnion(page, new URL("login", base).toString(), { waitUntil: "domcontentloaded" });
      const usernameField = page.getByRole("textbox", { name: shared.env.nextcloudUsernameFieldPattern });
      await expect(usernameField, "the native sign-in form must render").toBeVisible({ timeout: resolveTimeout(60_000) });
      await usernameField.fill(probe.username);
      await page.locator('input[name="password"]').first().fill(probe.password);
      await page.getByRole("button", { name: shared.env.nextcloudCredentialSubmitPattern }).click({ timeout: resolveTimeout(30_000) });

      await expect(page, "an account of an enforced group without a provider must land on the setup challenge").toHaveURL(
        /\/login\/setupchallenge/,
        { timeout: resolveTimeout(60_000) },
      );
      await expect(
        page.locator("h2").filter({ hasText: /set up two-factor authentication/i }).first(),
        "the setup challenge must ask the account to set up its second factor",
      ).toBeVisible({ timeout: resolveTimeout(30_000) });
      await expect(
        page.locator("a[href*='/login/setupchallenge/totp']").first(),
        "the TOTP provider must be offered for enrollment",
      ).toBeVisible({ timeout: resolveTimeout(30_000) });

      await gotoOnion(page, new URL("apps/files/", base).toString(), { waitUntil: "domcontentloaded" });
      await expect(page, "the Files app must hand the account back to the two-factor challenge").toHaveURL(
        /\/login\/(?:selectchallenge|setupchallenge)/,
        { timeout: resolveTimeout(60_000) },
      );
      await expect(page.locator(SHELL), "the account must not reach the Nextcloud shell before it enrolls").toHaveCount(0);

      await page.locator("#cancel-login").first().click({ timeout: resolveTimeout(30_000) });
      await expect(usernameField, "cancelling the challenge must end on the signed-out sign-in form").toBeVisible({
        timeout: resolveTimeout(60_000),
      });
    } finally {
      if (enforcing) {
        const restored = await call(request, "PUT", enforcementUrl, { headers: admin, data: previous }).then(
          (response) => response.status(),
          (error) => String(error),
        );
        if (restored !== 200) {
          console.warn(`restoring the two-factor enforcement state failed: ${restored}`);
        }
      }
      await call(request, "DELETE", ocs(`users/${encodeURIComponent(probe.username)}`), { headers: admin }).catch((error) =>
        console.warn(`deleting the probe account failed: ${error}`),
      );
      await call(request, "DELETE", ocs(`groups/${encodeURIComponent(group)}`), { headers: admin }).catch((error) =>
        console.warn(`deleting the probe group failed: ${error}`),
      );
    }
  });
};
