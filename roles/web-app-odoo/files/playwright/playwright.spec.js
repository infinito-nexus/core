const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { awaitOnionHandoff, decodeDotenvQuotedValue, isVisible, performKeycloakLoginForm, runAdminFlow, runBiberFlow, runGuestFlow, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { clickOdooSsoButton, onionOptions } = require("./_shared");

require("./test-seaweedfs");
require("./test-login-methods");
require("./test-2fa-enforcement");
const { env: rbacEnv, withBiberIn } = require("./test-rbac");

test.use({
  ignoreHTTPSErrors: true,
  ...onionOptions
});

// `docker --env-file` preserves the quotes emitted by `dotenv_quote`,
// so normalize these values before building URLs or typing credentials.
const oidcIssuerUrl     = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const odooBaseUrl       = decodeDotenvQuotedValue(process.env.ODOO_BASE_URL);
const adminUsername  = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword  = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername  = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword  = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);

// Check if user is authenticated in Odoo
// Odoo is a SPA - after login, the web client loads asynchronously.
// We check multiple indicators: the web client container, navbar elements,
// user menu, or the URL not being on the login page.
async function isOdooAuthenticated(locator) {
  try {
    // Primary indicators: web client root container that appears after successful load
    const webClient = locator.locator(".o_web_client");
    const actionManager = locator.locator(".o_action_manager");
    const mainNavbar = locator.locator(".o_main_navbar");
    
    // Secondary indicators: specific UI elements for logged-in users
    const userMenu = locator.locator(".o_user_menu");
    const appsIcon = locator.locator(".o_navbar_apps_menu, .o_menu_toggle");
    const homeMenu = locator.locator(".o_home_menu");
    
    // Any of these indicates successful authentication
    return (
      await webClient.first().isVisible().catch(() => false) ||
      await actionManager.first().isVisible().catch(() => false) ||
      await mainNavbar.first().isVisible().catch(() => false) ||
      await userMenu.first().isVisible().catch(() => false) ||
      await appsIcon.first().isVisible().catch(() => false) ||
      await homeMenu.first().isVisible().catch(() => false)
    );
  } catch {
    return false;
  }
}

async function logOutThroughTheUserMenu(page) {
  await page.locator("button.o_user_menu, .o_user_menu button").first().click({ timeout: resolveTimeout(30_000) });
  await page.locator('[data-menu="logout"]').first().click({ timeout: resolveTimeout(30_000) });
}

test.beforeEach(() => {
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
  expect(odooBaseUrl, "ODOO_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
});

test("odoo: the suite runs on one worker", async () => {
  expect(
    test.info().config.workers,
    "an OAuth sign-in ends every other session of the same account, so PLAYWRIGHT_MAX_WORKERS must keep the spec files that share the administrator on one worker"
  ).toBe(1);
});

// Scenario I: Odoo → SSO login as admin → verify authenticated → logout
// (dashboard-iframe mechanics covered by web-app-dashboard SPOT)
test("odoo: admin sso login, verify ui, logout", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  const expectedOdooBaseUrl = odooBaseUrl.replace(/\/$/, "");
  const odooLoginUrl = `${expectedOdooBaseUrl}/web/login`;

  // 1. Navigate directly to Odoo login
  await gotoOnion(page, odooLoginUrl);

  // 2. Click the "Login with SSO" button (waits internally for provider list)
  await clickOdooSsoButton(page);

  // 3. After clicking SSO, the page navigates to Keycloak.
  await awaitOnionHandoff(page, oidcIssuerUrl.replace(/\/$/, ""), async () => {
    await gotoOnion(page, odooLoginUrl);
    await clickOdooSsoButton(page);
  });

  // 4. Perform OIDC login with admin credentials
  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  // 5. Wait for navigation back to Odoo after authentication.
  // The URL must contain the Odoo base URL but NOT /web/login (which would mean auth failed).
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "Expected page to navigate back to Odoo authenticated area (not login page)"
    })
    .toMatch(new RegExp(`^${expectedOdooBaseUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?!/web/login)`));

  // 6. Verify the user is authenticated (Odoo shows apps/user menu)
  await expect
    .poll(
      async () => await isOdooAuthenticated(page),
      {
        timeout: resolveTimeout(60_000),
        message: "Expected Odoo to show authenticated user interface"
      }
    )
    .toBe(true);

  // 7. Log out through the user menu
  await logOutThroughTheUserMenu(page);

  // 8. Verify we're back on the login page (provider list visible again)
  await expect
    .poll(
      async () => await isVisible(page.locator(".o_login_auth, .o_auth_oauth_providers")),
      {
        timeout: resolveTimeout(60_000),
        message: "Expected Odoo to return to login page after logout"
      }
    )
    .toBe(true);
});

test("odoo: biber sso login, verify ui, logout", async ({ page, browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(240_000)); // group join, OAuth round-trip and group teardown
  await withBiberIn(browser, rbacEnv.groups.user, () => biberSsoJourney(page));
});

async function biberSsoJourney(page) {
  const expectedOdooBaseUrl = odooBaseUrl.replace(/\/$/, "");
  const odooLoginUrl = `${expectedOdooBaseUrl}/web/login`;

  // 1. Navigate directly to Odoo login
  await gotoOnion(page, odooLoginUrl);

  // 2. Click the "Login with SSO" button
  await clickOdooSsoButton(page);

  // 3. Wait for navigation to Keycloak
  await awaitOnionHandoff(page, oidcIssuerUrl.replace(/\/$/, ""), async () => {
    await gotoOnion(page, odooLoginUrl);
    await clickOdooSsoButton(page);
  });

  // 4. Perform OIDC login with biber credentials
  await performKeycloakLoginForm(page, biberUsername, biberPassword);

  // 5. Wait for navigation back to Odoo after authentication.
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "Expected page to navigate back to Odoo authenticated area (not login page)"
    })
    .toMatch(new RegExp(`^${expectedOdooBaseUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?!/web/login)`));

  // 6. Verify the user is authenticated
  await expect
    .poll(
      async () => await isOdooAuthenticated(page),
      {
        timeout: resolveTimeout(60_000),
        message: "Expected Odoo to show authenticated user interface for biber"
      }
    )
    .toBe(true);

  // 7. Log out through the user menu
  await logOutThroughTheUserMenu(page);

  // 8. Verify we're back on the login page
  await expect
    .poll(
      async () => await isVisible(page.locator(".o_login_auth, .o_auth_oauth_providers")),
      {
        timeout: resolveTimeout(60_000),
        message: "Expected Odoo to return to login page after logout"
      }
    )
    .toBe(true);
}

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas.js
// so every role's persona flow stays consistent.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page);
});

require("./test-design").register(require("./_shared"));
