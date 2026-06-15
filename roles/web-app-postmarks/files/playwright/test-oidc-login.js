const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.POSTMARKS_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

test.use({ ignoreHTTPSErrors: true });

test("OIDC: oauth2-proxy + trusted-header bridge mint a real Postmarks owner session", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "POSTMARKS_BASE_URL must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  await page.context().clearCookies();

  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedBase = baseUrl.replace(/\/$/, "");
  await page.goto(`${expectedBase}/`);
  await expect
    .poll(() => page.url(), { timeout: 60_000, message: `expected redirect to ${expectedAuth}` })
    .toContain(expectedAuth);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect
    .poll(() => page.url(), { timeout: 90_000, message: `expected redirect back to ${expectedBase}` })
    .toContain(expectedBase);
  await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });

  // Proof of a genuine authenticated app session (not just the proxy
  // round-trip): the upstream /admin gate (isAuthenticated -> req.session
  // .loggedIn) renders the admin surface instead of bouncing to /login.
  // The middleware only flips loggedIn when nginx-overwritten X-Forwarded-*
  // headers are present, so a passing /admin proves the bridge ran.
  const adminResponse = await page.goto(`${expectedBase}/admin`, { waitUntil: "domcontentloaded" });
  expect(adminResponse, "Expected a response from /admin").toBeTruthy();
  expect(
    adminResponse.status(),
    `the owner session must open /admin, got ${adminResponse.status()}`,
  ).toBeLessThan(400);
  expect(
    page.url(),
    `an authenticated owner must reach /admin, not be bounced to /login (at ${page.url()})`,
  ).not.toMatch(/\/login(\?|$)/);
  expect(
    new URL(page.url()).pathname,
    `expected to remain on the /admin surface (at ${page.url()})`,
  ).toMatch(/^\/admin/);
  await expect(page.locator("body")).toContainText(
    /bookmarks?|posts?|new bookmark|admin|settings|sign\s*out|logout/i,
    { timeout: 60_000 },
  );

  // The public page reflects the same owner session (res.locals.loggedIn
  // drives the admin / sign-out affordances).
  await page.goto(`${expectedBase}/`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("body")).toContainText(
    /admin|sign\s*out|logout|new bookmark/i,
    { timeout: 60_000 },
  );
});
