const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, normalizeBaseUrl, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const lamBaseUrl = normalizeBaseUrl(process.env.LAM_BASE_URL || "");
const lamPassword = decodeDotenvQuotedValue(process.env.LAM_PASSWORD);

exports.register = function (shared) {
  test.describe("keycloak → ldap write-through, verified via LAM", () => {
    test("middleName edited in Keycloak appears in LDAP via LAM", async ({ page, context }) => {
      skipUnlessServiceEnabled("sso");
      skipUnlessServiceEnabled("lam");
      expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set in env").toBeTruthy();
      expect(shared.env.oidcClientId, "OIDC_CLIENT_ID must be set in env").toBeTruthy();
      expect(lamBaseUrl, "LAM_BASE_URL must be set in env").toBeTruthy();

      const probe = `LAM-${Date.now()}`;

      await gotoOnion(page, `${shared.env.oidcIssuerUrl}/.well-known/openid-configuration`);
      const restResult = await page.evaluate(shared.setMiddleNameViaAccountRest, {
        issuer: shared.env.oidcIssuerUrl,
        clientId: shared.env.oidcClientId,
        username: shared.env.biberUsername,
        password: shared.env.biberPassword,
        middleName: probe,
        withRestore: false,
      });

      expect(
        restResult.stage,
        `Keycloak write must succeed: stage=${restResult.stage} status=${restResult.status}`
      ).toBe("ok");

      expect(lamPassword, "LAM_PASSWORD must be set").toBeTruthy();
      const lamPage = await context.newPage();
      await shared.signInToLam(lamPage, lamBaseUrl, shared.env.adminUsername, lamPassword);

      await lamPage.goto(`${lamBaseUrl}/lam/templates/lists/list.php?type=user`, { waitUntil: "load" });
      const filter = lamPage.locator("input[type='text'][name='filter_uid'], input[type='text'][name^='filter_']").first();
      if (await filter.isVisible().catch(() => false)) {
        await filter.fill(shared.env.biberUsername);
        await filter.press("Enter");
        await lamPage.waitForLoadState("networkidle");
      }
      const biberRow = lamPage.locator(`tr:has(td:text-is("${shared.env.biberUsername}"))`).first();
      await expect(biberRow, "biber must appear in LAM user list").toBeVisible({ timeout: resolveTimeout(30_000) });
      const biberEdit = biberRow.locator(`a[href*="edit.php"][href*="${shared.env.biberUsername}"]`).first();
      await expect(biberEdit, "biber row must expose an Edit link").toBeVisible({ timeout: resolveTimeout(10_000) });
      await biberEdit.click({ timeout: resolveTimeout(30_000) });
      await lamPage.waitForLoadState("networkidle");

      const initialsField = lamPage.locator("input[name='initials']").first();
      await expect(
        initialsField,
        `LAM-rendered LDAP entry for ${shared.env.biberUsername} must contain probe "${probe}" in its initials field`
      ).toHaveValue(probe, { timeout: resolveTimeout(30_000) });
    });
  });
};
