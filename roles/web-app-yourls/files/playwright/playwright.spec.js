const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

const { decodeDotenvQuotedValue, performKeycloakLoginForm, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
test.use({
  ignoreHTTPSErrors: true,
});

// `docker --env-file` preserves the quotes emitted by `dotenv_quote`,
// so normalize these values before building URLs or typing credentials.
const oidcIssuerUrl  = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const yourlsBaseUrl  = decodeDotenvQuotedValue(process.env.YOURLS_BASE_URL);
const adminUsername  = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword  = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername  = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword  = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);

// Perform SSO login via Keycloak.

test.beforeEach(() => {
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
  expect(yourlsBaseUrl, "YOURLS_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
});

// Scenario I: /admin/ requires SSO login — admin can access, biber is denied.
//
// YOURLS uses oauth2-proxy in ACL blacklist mode: the root URL is public
// (URL redirects work without login) but /admin/ is protected. Only members
// of the hierarchical Keycloak group `/roles/web-app-yourls/administrator`
// (post-005 layout) are allowed through. This scenario is the end-to-end
// proof that the hierarchical RBAC layout reaches oauth2-proxy's
// `allowed_groups` correctly.
test("yourls: admin sso login to admin panel, then logout", async ({
  page,
}) => {
  skipUnlessServiceEnabled("oidc");
  const base                = yourlsBaseUrl.replace(/\/$/, "");
    const adminUrl            = `${base}/admin/`;
    const expectedOidcAuthUrl = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;

    // 1. Navigate to /admin/ — oauth2-proxy redirects unauthenticated requests to Keycloak
    await page.goto(adminUrl);

    await expect
      .poll(() => page.url(), {
        timeout: 30_000,
        message: `Expected redirect to Keycloak OIDC auth: ${expectedOidcAuthUrl}`,
      })
      .toContain(expectedOidcAuthUrl);

    // 2. Log in as admin
    await performKeycloakLoginForm(page, adminUsername, adminPassword);

    // 3. After successful auth, oauth2-proxy redirects back to /admin/
    await expect
      .poll(() => page.url(), {
        timeout: 60_000,
        message: `Expected redirect back to YOURLS admin panel: ${adminUrl}`,
      })
      .toContain(adminUrl);

    // 4. Verify the YOURLS admin panel loaded — page title is always "YOURLS Administration"
    await expect(page).toHaveTitle(/yourls/i, { timeout: 30_000 });

    // 5. Logout via the universal logout endpoint
    await page.goto(`${base}/logout`, { waitUntil: "commit" }).catch(() => {});

    // 6. Verify session is gone — /admin/ redirects back to Keycloak
    await page.goto(adminUrl, { waitUntil: "domcontentloaded" });
    await expect
      .poll(() => page.url(), {
        timeout: 15_000,
        message: "Expected redirect to Keycloak after logout",
      })
      .toContain(expectedOidcAuthUrl);
});

// Scenario II: biber is denied access to /admin/ after SSO login
//
// biber is a regular authenticated Keycloak user but is NOT in the
// administrator group. oauth2-proxy must return HTTP 403 after biber
// completes the Keycloak login flow.
test("yourls: biber is denied access to /admin/ after sso login", async ({
  browser,
}) => {
  skipUnlessServiceEnabled("oidc");
  const base                = yourlsBaseUrl.replace(/\/$/, "");
    const expectedOidcAuthUrl = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;

    // Isolated browser context — no shared session with other tests
    const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });

    try {
      const biberPage = await biberContext.newPage();

      // Register the callback listener BEFORE goto — the redirect chain can complete
      // faster than a listener registered after performKeycloakLoginForm would start.
      const callbackResponsePromise = biberPage.waitForResponse(
        (res) => res.url().includes("/oauth2/callback"),
        { timeout: 60_000 }
      );

      // 1. Navigate to /admin/ — oauth2-proxy redirects to Keycloak
      await biberPage.goto(`${base}/admin/`);

      await expect
        .poll(() => biberPage.url(), {
          timeout: 30_000,
          message: `Expected redirect to Keycloak OIDC auth: ${expectedOidcAuthUrl}`,
        })
        .toContain(expectedOidcAuthUrl);

      // 2. Log in as biber
      await performKeycloakLoginForm(biberPage, biberUsername, biberPassword);

      // 3. oauth2-proxy callback must return 403 — biber is not in the admin group
      const callbackResponse = await callbackResponsePromise;

      expect(
        callbackResponse.status(),
        `Expected oauth2-proxy to deny biber with 403 at /oauth2/callback, got ${callbackResponse.status()}`
      ).toBe(403);
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
      // web-app-yourls admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|administration|tools|stats|users)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /admin|tools|stats|users|configuration/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
