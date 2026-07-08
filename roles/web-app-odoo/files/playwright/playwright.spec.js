const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, isVisible, performKeycloakLoginForm, runAdminFlow, runBiberFlow, runGuestFlow, gotoOnion } = require("./personas");
const { isServiceEnabled } = require("./service-gating");
test.use({
  ignoreHTTPSErrors: true
});

const oidcEnabled = isServiceEnabled("sso");

// `docker --env-file` preserves the quotes emitted by `dotenv_quote`,
// so normalize these values before building URLs or typing credentials.
const oidcIssuerUrl     = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const odooBaseUrl       = decodeDotenvQuotedValue(process.env.ODOO_BASE_URL);
const adminUsername  = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword  = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername  = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword  = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);

// Click the "Login with SSO" button on Odoo's login page.
// Odoo renders OAuth provider links inside a ".o_login_auth" container (modern
// layout; older variants used ".o_auth_oauth_providers"). The oe_login_form has
// class "d-none" when OAuth is enabled, so we wait for either container OR the
// SSO link itself directly.
async function clickOdooSsoButton(locator) {
  const providerList = locator.locator(".o_login_auth, .o_auth_oauth_providers");
  const ssoButton = locator
    .locator('a[href*="/auth_oauth/signin"], a[href*="auth_oauth/signin"]')
    .filter({ hasText: /login with sso|sign in with|continue with/i })
    .first();
  const ssoButtonByText = locator.getByRole("link", { name: /login with sso/i }).first();

  await Promise.any([
    providerList.first().waitFor({ state: "visible", timeout: resolveTimeout(60_000) }),
    ssoButton.waitFor({ state: "visible", timeout: resolveTimeout(60_000) }),
    ssoButtonByText.waitFor({ state: "visible", timeout: resolveTimeout(60_000) })
  ]);

  if (await ssoButtonByText.isVisible().catch(() => false)) {
    await ssoButtonByText.click();
  } else {
    await ssoButton.click();
  }
}

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

// Perform logout from Odoo by navigating directly to the logout URL.
async function performOdooLogout(page, odooBaseUrl) {
  const logoutUrl = `${odooBaseUrl.replace(/\/$/, "")}/web/session/logout`;

  await gotoOnion(page, logoutUrl);

  // Give the logout a moment to process
  await page.waitForTimeout(resolveTimeout(2_000));
}

test.beforeEach(() => {
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
  expect(odooBaseUrl, "ODOO_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
});

// Scenario I: Odoo → SSO login as admin → verify authenticated → logout
// (dashboard-iframe mechanics covered by web-app-dashboard SPOT)
test("odoo: admin sso login, verify ui, logout", async ({ page }) => {
  test.skip(!oidcEnabled, "OIDC shared service disabled");
  const expectedOdooBaseUrl = odooBaseUrl.replace(/\/$/, "");
  const odooLoginUrl = `${expectedOdooBaseUrl}/web/login`;

  // 1. Navigate directly to Odoo login
  await gotoOnion(page, odooLoginUrl);

  // 2. Click the "Login with SSO" button (waits internally for provider list)
  await clickOdooSsoButton(page);

  // 3. After clicking SSO, the page navigates to Keycloak.
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "Expected page to navigate to Keycloak for authentication"
    })
    .toContain(oidcIssuerUrl.replace(/\/$/, ""));

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

  // 7. Perform logout from Odoo by navigating to the logout URL
  await performOdooLogout(page, odooBaseUrl);

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

// Scenario II: Odoo → SSO login as biber (regular user) → verify authenticated → logout
//
// Similar to admin test but verifies regular (non-admin) user SSO flow works.
// Biber is a standard user without admin privileges - this confirms OIDC works
// for all Keycloak users, not just the administrator.
test("odoo: biber sso login, verify ui, logout", async ({ page }) => {
  test.skip(!oidcEnabled, "OIDC shared service disabled");
  const expectedOdooBaseUrl = odooBaseUrl.replace(/\/$/, "");
  const odooLoginUrl = `${expectedOdooBaseUrl}/web/login`;

  // 1. Navigate directly to Odoo login
  await gotoOnion(page, odooLoginUrl);

  // 2. Click the "Login with SSO" button
  await clickOdooSsoButton(page);

  // 3. Wait for navigation to Keycloak
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "Expected page to navigate to Keycloak for authentication"
    })
    .toContain(oidcIssuerUrl.replace(/\/$/, ""));

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

  // 7. Perform logout from Odoo
  await performOdooLogout(page, odooBaseUrl);

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
});

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
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // web-app-odoo admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(settings|users|companies|apps|administrator)$/i })
        .first();
      if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /settings|users|companies|apps|technical|developer/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
