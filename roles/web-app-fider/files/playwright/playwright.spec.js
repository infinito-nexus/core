const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, gotoOnion, performKeycloakLoginForm, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { clickFiderSsoButton } = require("./_shared");

require("./test-seaweedfs");
require("./test-mcp-guest").register();
require("./test-design").register();
require("./test-login-methods").register();

test.use({
  ignoreHTTPSErrors: true
});

// `docker --env-file` preserves the quotes emitted by `dotenv_quote`,
// so normalize these values before building URLs or typing credentials.
const oidcIssuerUrl     = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const fiderBaseUrl      = decodeDotenvQuotedValue(process.env.FIDER_BASE_URL);
const adminUsername  = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword  = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername  = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword  = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);

test.beforeEach(() => {
  expect(oidcIssuerUrl,  "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
  expect(fiderBaseUrl,   "FIDER_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername,  "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword,  "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername,  "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword,  "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
});

// Scenario I: Fider → SSO login as admin → verify admin UI → logout
// (dashboard-iframe mechanics covered by web-app-dashboard SPOT)
test("fider: admin sso login, verify ui, logout", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  const expectedFiderBaseUrl = fiderBaseUrl.replace(/\/$/, "");

  // 1. Navigate directly to Fider
  await gotoOnion(page, `${expectedFiderBaseUrl}/`);

  // 2. Click through Fider's sign-in flow to trigger the Keycloak SSO redirect
  await clickFiderSsoButton(page);

  // 3. Fider redirects to Keycloak for SSO login.
  //    (performKeycloakLoginForm waits for the username field before filling credentials.)
  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  // 4. After login Fider redirects back — verify the admin
  //    is logged in (.c-menu-user is only rendered when fider.session.isAuthenticated)
  await expect(page.locator(".c-menu-user").first()).toBeVisible({ timeout: resolveTimeout(60_000) });

  const usersResponse = await page.request.get(`${expectedFiderBaseUrl}/api/v1/users`);
  expect(
    usersResponse.status(),
    "the administrator role group MUST give the administrator the Fider administrator role, which lists the users",
  ).toBe(200);

  // 5. Logout — navigate to Fider's sign-out endpoint
  await gotoOnion(page, `${expectedFiderBaseUrl}/signout`, { waitUntil: "domcontentloaded" }).catch(() => {});

  // 6. Verify signout — the public Fider page should no longer show the user menu
  await gotoOnion(page, `${expectedFiderBaseUrl}/`);
  await expect(page.locator(".c-menu-user")).not.toBeAttached({ timeout: resolveTimeout(10_000) });
});

// Scenario II: biber logs in directly to Fider as a regular user → verifies access → logs out
//
// Fider is a public platform — any authenticated Keycloak user can log in.
// biber should be able to access Fider but will have a regular user role (not admin).
// This test verifies that the SSO flow works for non-admin users and that they land
// on the Fider main page (not an admin panel).
test("fider: biber sso login as regular user, verify access, logout", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  const expectedOidcAuthUrl  = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const expectedFiderBaseUrl = fiderBaseUrl.replace(/\/$/, "");

  // Isolated context — no shared session with other tests
  const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });

  try {
    const biberPage = await biberContext.newPage();

    // 1. Navigate directly to Fider
    await biberPage.goto(`${expectedFiderBaseUrl}/`);

    // 2. Fider public page loads — click Sign in → SSO provider
    await clickFiderSsoButton(biberPage);

    // 3. Wait for Keycloak OIDC auth
    await expect
      .poll(() => biberPage.url(), {
        timeout: resolveTimeout(30_000),
        message: `Expected redirect to Keycloak OIDC auth: ${expectedOidcAuthUrl}`
      })
      .toContain(expectedOidcAuthUrl);

    // 4. Log in as biber
    await performKeycloakLoginForm(biberPage, biberUsername, biberPassword);

    // 5. After login Fider redirects back
    await expect
      .poll(() => biberPage.url(), {
        timeout: resolveTimeout(60_000),
        message: `Expected redirect back to Fider after biber login: ${expectedFiderBaseUrl}`
      })
      .toContain(expectedFiderBaseUrl);

    // 6. Verify biber is logged in — .c-menu-user is only rendered when authenticated
    await expect(biberPage.locator(".c-menu-user").first()).toBeVisible({ timeout: resolveTimeout(30_000) });

    // 7. Verify biber is NOT shown admin controls.
    //    The admin link is inside the dropdown AND gated by isCollaborator — so it is
    //    never in the DOM for a regular user (regardless of dropdown state).
    await expect(biberPage.locator("a[href='/admin']").first()).not.toBeAttached({ timeout: resolveTimeout(5_000) });

    const usersResponse = await biberPage.request.get(`${expectedFiderBaseUrl}/api/v1/users`);
    expect(
      usersResponse.ok(),
      "biber holds no role group, so the deploy MUST keep the visitor role, which cannot list the users",
    ).toBe(false);

    // 8. Logout
    await biberPage.goto(`${expectedFiderBaseUrl}/signout`, { waitUntil: "domcontentloaded" }).catch(() => {});

  } finally {
    await biberContext.close().catch(() => {});
  }
});

test("administrator: Fider lists biber with the name claim and the visitor role", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000)); // two Keycloak round trips, biber then the administrator
  const biberFullName = decodeDotenvQuotedValue(process.env.BIBER_FULL_NAME);
  expect(biberFullName, "BIBER_FULL_NAME must be set in the Playwright env file").toBeTruthy();
  const expectedFiderBaseUrl = fiderBaseUrl.replace(/\/$/, "");

  const signIn = async (username, password) => {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();
    await gotoOnion(page, `${expectedFiderBaseUrl}/`);
    await clickFiderSsoButton(page);
    await performKeycloakLoginForm(page, username, password);
    await expect(page.locator(".c-menu-user").first()).toBeVisible({ timeout: resolveTimeout(60_000) });
    return { context, page };
  };

  const biber = await signIn(biberUsername, biberPassword);
  await biber.context.close().catch(() => {});

  const admin = await signIn(adminUsername, adminPassword);
  try {
    const usersResponse = await admin.page.request.get(
      `${expectedFiderBaseUrl}/api/v1/users?query=${encodeURIComponent(biberFullName)}&limit=100`,
    );
    expect(usersResponse.status(), "the administrator MUST list the Fider users").toBe(200);
    const listing = await usersResponse.json();
    expect(
      Array.isArray(listing?.users),
      `Fider MUST answer a page of users (got the keys ${JSON.stringify(Object.keys(listing ?? {}))})`,
    ).toBe(true);
    const biberAccount = listing.users.find((user) => user.name === biberFullName);
    expect(biberAccount, `json_user_name_path MUST read the name claim, so a user named "${biberFullName}" exists`).toBeTruthy();
    expect(biberAccount.role, "biber holds no role group, so the deploy keeps the visitor role").toBe("visitor");
  } finally {
    await admin.context.close().catch(() => {});
  }
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
  await runAdminFlow(page);
});
