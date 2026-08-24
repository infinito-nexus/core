const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { assertCspMetaParity, assertCspResponseHeader, decodeDotenvQuotedValue, expectNoCspViolations, gotoOnion, installCspViolationObserver, normalizeBaseUrl, runAdminFlow, runBiberFlow, runGuestFlow, safeSkipUnlessEnabled } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

// -----------------------------------------------------------------------------
// Shared helpers (inlined on purpose: the runner only stages this file).
// -----------------------------------------------------------------------------

function attachDiagnostics(page) {
  const consoleErrors = [];
  const pageErrors = [];
  const cspRelated = [];

  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }

    if (/content security policy|csp/i.test(message.text())) {
      cspRelated.push({ source: "console", text: message.text() });
    }
  });

  page.on("pageerror", (error) => {
    const text = String(error);
    pageErrors.push(text);

    if (/content security policy|csp/i.test(text)) {
      cspRelated.push({ source: "pageerror", text });
    }
  });

  return { consoleErrors, pageErrors, cspRelated };
}

async function fillKeycloakLoginForm(page, username, password) {
  const usernameField = page.locator("input[name='username'], input#username").first();
  const passwordField = page.locator("input[name='password'], input#password").first();
  const signInButton = page
    .locator("input#kc-login, button#kc-login, button[type='submit'], input[type='submit']")
    .first();

  await expect(usernameField, "Expected Keycloak username field to be visible").toBeVisible({ timeout: resolveTimeout(60_000) });
  await usernameField.fill(username);
  await passwordField.fill(password);
  await signInButton.click({ timeout: resolveTimeout(30_000) });
}

async function keycloakSignOutFromAccountConsole(page) {
  const signOutButton = page
    .locator("button, a")
    .filter({ hasText: /sign\s*out|logout|abmelden/i })
    .first();

  if ((await signOutButton.count().catch(() => 0)) === 0) {
    return;
  }

  await signOutButton.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
  await page.waitForLoadState("networkidle").catch(() => {});
}

async function keycloakSignOutFromMasterAdminConsole(page, appBaseUrl) {
  await page
    .goto(`${appBaseUrl}/realms/master/protocol/openid-connect/logout`, { waitUntil: "commit" })
    .catch(() => {});
  await page.context().clearCookies().catch(() => {});
}

// -----------------------------------------------------------------------------
// Test configuration
// -----------------------------------------------------------------------------

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const realmName = decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME);
const superAdminUsername = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME);
const superAdminPassword = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });

  expect(appBaseUrl, "APP_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(realmName, "KEYCLOAK_REALM_NAME must be set in the Playwright env file").toBeTruthy();
  expect(superAdminUsername, "SUPER_ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(superAdminPassword, "SUPER_ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set in the Playwright env file").toBeTruthy();

  await page.context().clearCookies();
  await installCspViolationObserver(page);
});

test("keycloak enforces Content-Security-Policy and exposes canonical domain from applications lookup", async ({ page }) => {
  const diagnostics = attachDiagnostics(page);

  const response = await gotoOnion(page, `${appBaseUrl}/realms/${realmName}/account/`);
  expect(response, "Expected Keycloak account page response").toBeTruthy();
  expect(response.status(), "Expected Keycloak account page to respond successfully").toBeLessThan(400);

  const directives = assertCspResponseHeader(response, "keycloak account page");
  await assertCspMetaParity(page, directives, "keycloak account page");

  const documentHtml = await response.text();
  expect(
    documentHtml.includes(canonicalDomain) || (await page.content()).includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" (from applications lookup) to appear in the Keycloak UI`
  ).toBe(true);

  await expectNoCspViolations(page, diagnostics, "keycloak account page");
});

test("master-realm super administrator logs into Keycloak admin console and logs out", async ({ page }) => {
  const diagnostics = attachDiagnostics(page);

  const response = await gotoOnion(page,`${appBaseUrl}/admin/master/console/`);
  expect(response, "Expected Keycloak admin console response").toBeTruthy();
  expect(response.status(), "Expected Keycloak admin console response to be successful").toBeLessThan(400);

  assertCspResponseHeader(response, "keycloak admin console");

  await fillKeycloakLoginForm(page, superAdminUsername, superAdminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "Expected super admin login to leave the Keycloak login page"
    })
    .not.toContain("/login-actions/authenticate");

  await expect(page.locator("body")).toContainText(/master|realm|clients|users/i, { timeout: resolveTimeout(60_000) });

  await keycloakSignOutFromMasterAdminConsole(page, appBaseUrl);

  await gotoOnion(page,`${appBaseUrl}/admin/master/console/`);
  await expect(
    page.locator("input[name='username'], input#username").first(),
    "Expected Keycloak admin console to require login again after sign out"
  ).toBeVisible({ timeout: resolveTimeout(60_000) });

  await expectNoCspViolations(page, diagnostics, "keycloak admin console");
});

test("normal-realm administrator logs in through account interface and logs out", async ({ page }) => {
  const diagnostics = attachDiagnostics(page);

  const accountUrl = `${appBaseUrl}/realms/${realmName}/account/`;
  const response = await gotoOnion(page,accountUrl);
  expect(response, "Expected normal-realm account page response").toBeTruthy();
  expect(response.status(), "Expected normal-realm account page response to be successful").toBeLessThan(400);

  assertCspResponseHeader(response, "keycloak normal-realm account (administrator)");

  const signInButton = page.locator("a, button").filter({ hasText: /sign\s*in|log\s*in|anmelden/i }).first();

  if ((await signInButton.count().catch(() => 0)) > 0) {
    await signInButton.click({ timeout: resolveTimeout(30_000) });
  }

  await fillKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "Expected administrator login to reach the account interface"
    })
    .toContain("/account");

  await expect(page.locator("body")).toContainText(new RegExp(adminUsername, "i"), { timeout: resolveTimeout(60_000) });

  await keycloakSignOutFromAccountConsole(page);

  await gotoOnion(page,accountUrl);
  const postLogoutSignIn = page.locator("a, button").filter({ hasText: /sign\s*in|log\s*in|anmelden/i }).first();
  const usernameField = page.locator("input[name='username'], input#username").first();

  await expect
    .poll(
      async () =>
        (await postLogoutSignIn.count().catch(() => 0)) > 0 || (await usernameField.count().catch(() => 0)) > 0,
      {
        timeout: resolveTimeout(60_000),
        message: "Expected account interface to require login again after administrator sign out"
      }
    )
    .toBe(true);

  await expectNoCspViolations(page, diagnostics, "keycloak normal-realm account (administrator)");
});

test("normal-realm biber logs in through account interface and logs out", async ({ page }) => {
  safeSkipUnlessEnabled("ldap");
  const diagnostics = attachDiagnostics(page);

  const accountUrl = `${appBaseUrl}/realms/${realmName}/account/`;
  const response = await gotoOnion(page,accountUrl);
  expect(response, "Expected normal-realm account page response").toBeTruthy();
  expect(response.status(), "Expected normal-realm account page response to be successful").toBeLessThan(400);

  assertCspResponseHeader(response, "keycloak normal-realm account (biber)");

  const signInButton = page.locator("a, button").filter({ hasText: /sign\s*in|log\s*in|anmelden/i }).first();

  if ((await signInButton.count().catch(() => 0)) > 0) {
    await signInButton.click({ timeout: resolveTimeout(30_000) });
  }

  await fillKeycloakLoginForm(page, biberUsername, biberPassword);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "Expected biber login to reach the account interface"
    })
    .toContain("/account");

  await expect(page.locator("body")).toContainText(/personal\s*info|account|profile|signing\s*in/i, { timeout: resolveTimeout(60_000) });

  await keycloakSignOutFromAccountConsole(page);

  await gotoOnion(page,accountUrl);
  const postLogoutSignIn = page.locator("a, button").filter({ hasText: /sign\s*in|log\s*in|anmelden/i }).first();
  const usernameField = page.locator("input[name='username'], input#username").first();

  await expect
    .poll(
      async () =>
        (await postLogoutSignIn.count().catch(() => 0)) > 0 || (await usernameField.count().catch(() => 0)) > 0,
      {
        timeout: resolveTimeout(60_000),
        message: "Expected account interface to require login again after biber sign out"
      }
    )
    .toBe(true);

  await expectNoCspViolations(page, diagnostics, "keycloak normal-realm account (biber)");
});

// Persona scenarios — auth-provider exception.
//
// web-app-keycloak IS the OIDC / OAuth2 / LDAP-federation auth provider
// itself. The generic persona-flow runners assume a downstream app
// behind a Keycloak chain; for keycloak that journey is circular (the
// "app" behind keycloak IS keycloak). The persona-equivalent coverage
// for this role lives in the bespoke role-specific tests above:
//
//   - "keycloak enforces Content-Security-Policy and exposes canonical
//     domain from applications lookup"
//                              → guest persona equivalent.
//   - "master-realm super administrator logs into Keycloak admin
//     console and logs out"   → administrator persona equivalent.
//   - "normal-realm administrator logs in through account interface
//     and logs out"            → administrator persona via account UI.
//   - "normal-realm biber logs in through account interface and logs
//     out"                     → biber persona via account UI.
//
// No generic persona scenarios are emitted; the auth-provider role is
// part of the auth-less / circular-dependency persona-collapse
// exception.

// Persona scenarios.
// Bodies live in the shared persona helpers under
// roles/test-e2e-playwright/files/personas/{guest,biber,admin}.js.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → keycloak → role action → logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → keycloak → admin action → logout", async ({ page }) => {
  await runAdminFlow(page);
});
