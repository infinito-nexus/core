const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled, isServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.BOOKWYRM_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

test.use({ ignoreHTTPSErrors: true });

test("oidc-security: a forged identity header cannot bypass the oauth2-proxy gate", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "BOOKWYRM_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");

  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: { "X-Forwarded-Preferred-Username": "administrator" },
  });
  try {
    const page = await context.newPage();
    await page.goto(`${expectedBase}/preferences/profile`, { waitUntil: "domcontentloaded" });

    await expect
      .poll(() => page.url(), { timeout: 60_000 })
      .toContain("openid-connect/auth");
    await expect(
      page.locator('form[name="edit-profile"]'),
      "a forged identity header must NOT yield an authenticated BookWyrm session",
    ).toHaveCount(0);
  } finally {
    await context.close();
  }
});

test("oidc-security: the trusted-header bridge stays inert while SSO is disabled", async ({ browser }) => {
  test.skip(isServiceEnabled("sso"), "SSO enabled — forged-header gating is covered by the test above");
  expect(baseUrl, "BOOKWYRM_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: { "X-Forwarded-Preferred-Username": "administrator" },
  });
  try {
    const page = await context.newPage();
    await page.goto(`${expectedBase}/preferences/profile`, { waitUntil: "domcontentloaded" });
    await expect(
      page.locator('form[name="edit-profile"]'),
      "a forged identity header must NOT yield an authenticated BookWyrm session while SSO is disabled",
    ).toHaveCount(0);
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
  await page.goto(`${expectedBase}/`);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect
    .poll(() => page.url(), { timeout: 90_000, message: `expected redirect back to ${expectedBase}` })
    .toContain(expectedBase.replace(/^https?:\/\//, ""));

  await page.goto(`${expectedBase}/preferences/profile`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator('form[name="edit-profile"]'),
    "the genuine oauth2 session must be authenticated before the injection probe",
  ).toBeVisible({ timeout: 30_000 });

  const forgedMarker = "forgedescalationprobe";
  await page.setExtraHTTPHeaders({
    "X-Forwarded-Preferred-Username": forgedMarker,
    "X-Forwarded-User": forgedMarker,
    "X-Forwarded-Email": `${forgedMarker}@attacker.invalid`,
    "X-Auth-Request-Preferred-Username": forgedMarker,
    "X-Auth-Request-User": forgedMarker,
    "X-Auth-Request-Email": `${forgedMarker}@attacker.invalid`,
    "Remote-User": forgedMarker,
  });
  await page.goto(`${expectedBase}/preferences/profile`, { waitUntil: "domcontentloaded" });

  await expect(
    page.locator('form[name="edit-profile"]'),
    "the genuine oauth2 session must survive the injection probe",
  ).toBeVisible({ timeout: 30_000 });
  expect(
    (await page.content()).toLowerCase(),
    "the oauth2-proxy identity must win; an injected header must not switch the BookWyrm session",
  ).not.toContain(forgedMarker);
});
