const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");

const joomlaBaseUrl = normalizeBaseUrl(process.env.JOOMLA_BASE_URL);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.use({ ignoreHTTPSErrors: true });

async function performJoomlaAdminFormLogin(page, baseUrl, username, password) {
  // Local Joomla form-login at /administrator?fallback=local. The
  // `?fallback=local` query short-circuits the plg_system_keycloak
  // redirect so the operator has an emergency hatch when Keycloak is
  // unavailable (per the documented Modus 3 contract).
  await page.goto(`${baseUrl}/administrator?fallback=local`, { waitUntil: "domcontentloaded" });

  const usernameField = page.locator("input[name='username']");
  const passwordField = page.locator("input[name='passwd']");

  await usernameField.waitFor({ state: "visible", timeout: 60_000 });
  await usernameField.fill(username);
  await passwordField.fill(password);

  await Promise.all([
    page.waitForLoadState("domcontentloaded"),
    page.locator("button[type='submit'], input[type='submit']").first().click(),
  ]);
}

test("OIDC: /administrator?fallback=local hatch bypasses Keycloak and accepts the local Joomla form (Modus 3 emergency path)", async ({ page }) => {
  // The local form-login fallback at /administrator?fallback=local
  // is the operationally-mandated hatch when Keycloak is unavailable
  // (per the documented Modus 3 contract). It MUST NOT redirect to the IdP,
  // and the local form MUST accept the bootstrap administrator
  // credentials.
  expect(joomlaBaseUrl, "JOOMLA_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  await page.context().clearCookies();
  skipUnlessServiceEnabled("sso");
  const expectedJoomlaBaseUrl = joomlaBaseUrl.replace(/\/$/, "");

  await performJoomlaAdminFormLogin(page, expectedJoomlaBaseUrl, adminUsername, adminPassword);

  // Joomla 6 uses `body.com_cpanel` on the admin home; the broader
  // fallback set covers future template tweaks.
  const controlPanelMarker = page
    .locator("body.com_cpanel, #sidebarmenu, nav[aria-label='Main menu'], a[href*='option=com_cpanel']")
    .first();
  await controlPanelMarker.waitFor({ state: "visible", timeout: 60_000 });
});
