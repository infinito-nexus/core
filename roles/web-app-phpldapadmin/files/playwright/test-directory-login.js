const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled, isServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginExpectingDenial,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");

const baseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const admin = {
  username: decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME")),
  password: decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD")),
};
const biber = {
  username: decodeDotenvQuotedValue(requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME")),
  password: decodeDotenvQuotedValue(requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD")),
};
const LOGIN_USER = "form input#user";
const LOGIN_PASSWORD = "form input#password";

async function openLoginForm(page) {
  await gotoOnion(page, `${baseUrl}/login`);
  if (isServiceEnabled("sso") && page.url().includes("openid-connect/auth")) {
    await performKeycloakLoginForm(page, admin.username, admin.password);
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(90_000), message: `expected redirect back to ${baseUrl}` })
      .toContain(baseUrl);
    await gotoOnion(page, `${baseUrl}/login`);
  }
  await expect(page.locator(LOGIN_USER)).toBeEditable({ timeout: resolveTimeout(30_000) });
}

exports.register = function () {
  test("directory login: the administrator signs in to phpLDAPadmin with its directory user name", async ({ page }) => {
    await page.context().clearCookies();
    await openLoginForm(page);
    await page.locator(LOGIN_USER).fill(admin.username);
    await page.locator(LOGIN_PASSWORD).fill(admin.password);
    await page.getByRole("button", { name: /^login$/i }).click();
    await expect(page.locator("a#user"), "the bind as the administrator's own entry must open a session").toBeVisible({
      timeout: resolveTimeout(60_000),
    });
  });

  test("rbac: biber without the phpLDAPadmin administrator role is denied at the oauth2-proxy gate", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    await page.context().clearCookies();
    await gotoOnion(page, `${baseUrl}/`);
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected the oauth2-proxy redirect to Keycloak" })
      .toContain("openid-connect/auth");
    await performKeycloakLoginExpectingDenial(page, biber.username, biber.password, canonicalDomain);
  });
};
