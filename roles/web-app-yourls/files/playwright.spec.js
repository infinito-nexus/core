const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

test.use({
  ignoreHTTPSErrors: true,
});

function decodeDotenvQuotedValue(value) {
  if (typeof value !== "string" || value.length < 2) {
    return value;
  }

  if (!(value.startsWith('"') && value.endsWith('"'))) {
    return value;
  }

  const encoded = value.slice(1, -1);

  try {
    return JSON.parse(`"${encoded}"`).replace(/\$\$/g, "$");
  } catch {
    return encoded.replace(/\$\$/g, "$");
  }
}

// `docker --env-file` preserves the quotes emitted by `dotenv_quote`,
// so normalize these values before building URLs or typing credentials.
const oidcIssuerUrl  = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const yourlsBaseUrl  = decodeDotenvQuotedValue(process.env.YOURLS_BASE_URL);
const adminUsername  = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword  = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername  = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword  = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);

// Perform SSO login via Keycloak.
async function performOidcLogin(locator, username, password) {
  const usernameField = locator.getByRole("textbox", { name: /username|email/i });
  const passwordField = locator.getByRole("textbox", { name: "Password" });
  const signInButton  = locator.getByRole("button", { name: /sign in/i });

  await usernameField.waitFor({ state: "visible", timeout: 60_000 });
  await usernameField.fill(username);
  await usernameField.press("Tab");
  await passwordField.fill(password);
  await signInButton.click();
}

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
// proof that requirement 005's hierarchical RBAC layout reaches oauth2-proxy's
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
    await performOidcLogin(page, adminUsername, adminPassword);

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
      // faster than a listener registered after performOidcLogin would start.
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
      await performOidcLogin(biberPage, biberUsername, biberPassword);

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
