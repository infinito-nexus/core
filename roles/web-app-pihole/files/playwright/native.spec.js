// @ts-check
// Scenario: Native admin login (Keycloak not enabled)
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceDisabled } = require("./service-gating");

test.use({ ignoreHTTPSErrors: true });

const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const piholeBaseUrl = decodeDotenvQuotedValue(process.env.PIHOLE_BASE_URL);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.beforeEach(() => {
  skipUnlessServiceDisabled("sso");
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must stay unset while the sso service is disabled").toBeFalsy();
  expect(piholeBaseUrl, "PIHOLE_BASE_URL must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
});

test("administrator: can log in natively to pihole", async ({ page }) => {
  const expectedPiholeBaseUrl = piholeBaseUrl.replace(/\/$/, "");

  await gotoOnion(page, `${expectedPiholeBaseUrl}/admin/login`);
  await page.waitForLoadState("networkidle", { timeout: resolveTimeout(30_000) }).catch(() => {});

  const passwordInput = page.getByRole("textbox", { name: /password/i });
  await passwordInput.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await passwordInput.fill(adminPassword);
  // Pi-hole v6 login button text is "Log in (uses cookie)"
  await page.getByRole("button", { name: /log in|sign in/i }).click({ timeout: resolveTimeout(30_000) });

  await page.waitForLoadState("networkidle", { timeout: resolveTimeout(30_000) }).catch(() => {});
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `native login must leave the login form, still at ${page.url()}`,
    })
    .not.toContain("/login");
  await expect(passwordInput).toBeHidden({ timeout: resolveTimeout(30_000) });
  await page.locator(".navbar-custom-menu .navbar-nav").waitFor({ state: "attached", timeout: resolveTimeout(30_000) });
  await expect(page.locator("#oauth2-logout-btn"), "the OAuth2 logout link must not be injected without SSO").toHaveCount(0);
});
