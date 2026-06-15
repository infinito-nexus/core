const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, performKeycloakLoginForm, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const { isServiceEnabled } = require("./service-gating");

require("./test-seaweedfs");

test.use({
  ignoreHTTPSErrors: true
});

const oidcEnabled = isServiceEnabled("sso");

// `docker --env-file` preserves the quotes emitted by `dotenv_quote`,
// so normalize these values before building URLs or typing credentials.
const oidcIssuerUrl     = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const fiderBaseUrl      = decodeDotenvQuotedValue(process.env.FIDER_BASE_URL);
const adminUsername  = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword  = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername  = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword  = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);

// Click through Fider's sign-in page to reach the SSO provider button.
// Fider shows a "Sign in" button in the header, then a modal listing OAuth providers.
async function clickFiderSsoButton(locator) {
  // Click "Sign in" in the Fider header
  const signInLink = locator.getByRole("link", { name: /sign in/i });

  await signInLink.first().waitFor({ state: "visible", timeout: 30_000 });
  await signInLink.first().click();

  // Fider shows a "Join the conversation" modal with a "Continue with ... SSO" button.
  // The display_name is set to "{{ SOFTWARE_NAME }} SSO" = "Infinito.Nexus SSO".
  const ssoButton = locator.getByRole("link", { name: /continue with/i });

  await ssoButton.first().waitFor({ state: "visible", timeout: 15_000 });
  // force: true bypasses aria-disabled which Fider sets on the button during modal render
  await ssoButton.first().click({ force: true });
}

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
  test.skip(!oidcEnabled, "OIDC shared service disabled");
  const expectedFiderBaseUrl = fiderBaseUrl.replace(/\/$/, "");

  // 1. Navigate directly to Fider
  await page.goto(`${expectedFiderBaseUrl}/`);

  // 2. Click through Fider's sign-in flow to trigger the Keycloak SSO redirect
  await clickFiderSsoButton(page);

  // 3. Fider redirects to Keycloak for SSO login.
  //    (performKeycloakLoginForm waits for the username field before filling credentials.)
  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  // 4. After login Fider redirects back — verify the admin
  //    is logged in (.c-menu-user is only rendered when fider.session.isAuthenticated)
  await expect(page.locator(".c-menu-user").first()).toBeVisible({ timeout: 60_000 });

  // 5. Logout — navigate to Fider's sign-out endpoint
  await page.goto(`${expectedFiderBaseUrl}/signout`, { waitUntil: "domcontentloaded" }).catch(() => {});

  // 6. Verify signout — the public Fider page should no longer show the user menu
  await page.goto(`${expectedFiderBaseUrl}/`);
  await expect(page.locator(".c-menu-user")).not.toBeAttached({ timeout: 10_000 });
});

// Scenario II: biber logs in directly to Fider as a regular user → verifies access → logs out
//
// Fider is a public platform — any authenticated Keycloak user can log in.
// biber should be able to access Fider but will have a regular user role (not admin).
// This test verifies that the SSO flow works for non-admin users and that they land
// on the Fider main page (not an admin panel).
test("fider: biber sso login as regular user, verify access, logout", async ({ browser }) => {
  test.skip(!oidcEnabled, "OIDC shared service disabled");
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
        timeout: 30_000,
        message: `Expected redirect to Keycloak OIDC auth: ${expectedOidcAuthUrl}`
      })
      .toContain(expectedOidcAuthUrl);

    // 4. Log in as biber
    await performKeycloakLoginForm(biberPage, biberUsername, biberPassword);

    // 5. After login Fider redirects back
    await expect
      .poll(() => biberPage.url(), {
        timeout: 60_000,
        message: `Expected redirect back to Fider after biber login: ${expectedFiderBaseUrl}`
      })
      .toContain(expectedFiderBaseUrl);

    // 6. Verify biber is logged in — .c-menu-user is only rendered when authenticated
    await expect(biberPage.locator(".c-menu-user").first()).toBeVisible({ timeout: 30_000 });

    // 7. Verify biber is NOT shown admin controls.
    //    The admin link is inside the dropdown AND gated by isCollaborator — so it is
    //    never in the DOM for a regular user (regardless of dropdown state).
    await expect(biberPage.locator("a[href='/admin']").first()).not.toBeAttached({ timeout: 5_000 });

    // 8. Logout
    await biberPage.goto(`${expectedFiderBaseUrl}/signout`, { waitUntil: "domcontentloaded" }).catch(() => {});

  } finally {
    await biberContext.close().catch(() => {});
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
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // web-app-fider admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|posts|users|invitations|settings)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /posts|administration|invitations|users|settings|tags/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
