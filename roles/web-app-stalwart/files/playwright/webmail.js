const { expect } = require("@playwright/test");

const { performKeycloakLoginForm, gotoOnion, waitForEmailInMailbox } = require("./personas");
const { webmailBaseUrl, expectedOidcAuthUrl } = require("./env");
const { resolveTimeout } = require("./timeouts");

async function roundcubeSsoLogin(page, username, password) {
  await gotoOnion(page, `${webmailBaseUrl}/`);
  const ssoButton = page
    .getByRole("button", { name: /sso|single sign.?on|login with|openid/i })
    .or(page.getByRole("link", { name: /sso|single sign.?on|login with|openid/i }));
  if (await ssoButton.first().isVisible().catch(() => false)) {
    await ssoButton.first().click();
  }
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `Expected redirect to Keycloak OIDC: ${expectedOidcAuthUrl}`,
    })
    .toContain(expectedOidcAuthUrl);
  await performKeycloakLoginForm(page, username, password);
  await page.locator("#messagelist, .compose, a[href*='_action=compose'], .toolbar").first()
    .waitFor({ state: "visible", timeout: resolveTimeout(60_000) });
}

async function roundcubeLogout(page) {
  const logout = page.locator("a[href*='_task=logout'], a[href*='logout'], a.logout")
    .or(page.getByRole("link", { name: /logout|sign out/i }));
  await expect(logout.first(), "Roundcube logout control must be present").toBeVisible({
    timeout: resolveTimeout(10_000),
  });
  await logout.first().click();
}

module.exports = { roundcubeSsoLogin, roundcubeLogout, waitForEmailInMailbox };
