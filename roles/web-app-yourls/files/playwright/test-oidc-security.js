const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled, isServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.YOURLS_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

const FORGED_IDENTITY_HEADERS = {
  "X-Forwarded-Preferred-Username": "administrator",
  "X-Forwarded-User": "administrator",
  "X-Forwarded-Email": "administrator@example.com",
  "X-Forwarded-Groups": "/roles/web-app-yourls/administrator",
};

test.use({ ignoreHTTPSErrors: true });

test("oidc-security: a forged identity header cannot bypass the oauth2-proxy gate", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "YOURLS_BASE_URL must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: FORGED_IDENTITY_HEADERS,
  });
  try {
    const page = await context.newPage();
    await page.goto(`${expectedBase}/admin/`, { waitUntil: "domcontentloaded" });

    await expect
      .poll(() => page.url(), {
        timeout: 60_000,
        message: "a forged identity header must be bounced to Keycloak, never into the YOURLS admin",
      })
      .toContain("openid-connect/auth");

    await expect(
      page.locator('a[href*="action=logout"]'),
      "no authenticated YOURLS admin session may be minted from a forged header",
    ).toHaveCount(0);
  } finally {
    await context.close();
  }
});

test("oidc-security: the trusted-header bridge stays inert while SSO is disabled", async ({ browser }) => {
  test.skip(isServiceEnabled("sso"), "SSO enabled — forged-header gating is covered by the test above");
  expect(baseUrl, "YOURLS_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: FORGED_IDENTITY_HEADERS,
  });
  try {
    const page = await context.newPage();
    await page.goto(`${expectedBase}/admin/`, { waitUntil: "domcontentloaded" });

    await expect(
      page.locator('a[href*="action=logout"]'),
      "a forged identity header must never mint a YOURLS admin session while SSO is disabled",
    ).toHaveCount(0);
    await expect(
      page.locator('input#password[name="password"]'),
      "with SSO disabled and the bridge inert, YOURLS must fall back to its own login form",
    ).toBeVisible({ timeout: 30_000 });
  } finally {
    await context.close();
  }
});

test("oidc-security: injected identity headers cannot re-identify an authenticated session", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  await page.context().clearCookies();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const adminUrl = `${expectedBase}/admin/`;

  await page.goto(adminUrl);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect
    .poll(() => page.url(), { timeout: 90_000, message: `expected redirect back to ${adminUrl}` })
    .toContain(adminUrl);

  await page.goto(adminUrl, { waitUntil: "domcontentloaded" });
  await expect(
    page
      .locator('a[href*="action=logout"], a[href*="openid-connect/logout"]')
      .or(page.getByRole("link", { name: /log\s*out/i })),
    "the genuine oauth2 session must be authenticated before the injection probe",
  ).toBeVisible({ timeout: 30_000 });

  const forgedMarker = "forgedescalationprobe";
  await page.setExtraHTTPHeaders({
    "X-Forwarded-Preferred-Username": forgedMarker,
    "X-Forwarded-User": forgedMarker,
    "X-Forwarded-Email": `${forgedMarker}@attacker.invalid`,
    "X-Forwarded-Name": forgedMarker,
    "X-Forwarded-Groups": "/roles/web-app-yourls/administrator",
    "X-Auth-Request-Preferred-Username": forgedMarker,
    "X-Auth-Request-User": forgedMarker,
    "X-Auth-Request-Email": `${forgedMarker}@attacker.invalid`,
    "Remote-User": forgedMarker,
  });
  await page.goto(adminUrl, { waitUntil: "domcontentloaded" });

  await expect(
    page
      .locator('a[href*="action=logout"], a[href*="openid-connect/logout"]')
      .or(page.getByRole("link", { name: /log\s*out/i })),
    "the genuine oauth2 session must survive the injection probe",
  ).toBeVisible({ timeout: 30_000 });
  expect(
    (await page.content()).toLowerCase(),
    "the oauth2-proxy identity must win; an injected header must not switch the YOURLS_USER",
  ).not.toContain(forgedMarker);
});
