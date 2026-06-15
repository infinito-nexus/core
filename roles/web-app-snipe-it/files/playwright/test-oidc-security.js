const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled, isServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.SNIPE_IT_BASE_URL || process.env.APP_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

const FORGED_IDENTITY_HEADERS = {
  "X-Forwarded-Preferred-Username": "administrator",
  "X-Forwarded-User": "administrator",
  "X-Forwarded-Email": "administrator@example.com",
  "X-Forwarded-Groups": "/roles/web-app-snipe-it/administrator",
};

test.use({ ignoreHTTPSErrors: true });

test("oidc-security: a forged identity header cannot bypass the oauth2-proxy gate on /login", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "SNIPE_IT_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: FORGED_IDENTITY_HEADERS,
  });
  try {
    const page = await context.newPage();
    await page.goto(`${expectedBase}/login`, { waitUntil: "domcontentloaded" });

    await expect
      .poll(() => page.url(), {
        timeout: 60_000,
        message: "a forged identity header on /login must be bounced to Keycloak, never trusted",
      })
      .toContain("openid-connect/auth");

    const sessionCookies = await context.cookies(expectedBase);
    expect(
      sessionCookies.some((cookie) => cookie.name === "snipeit_session" && Boolean(cookie.value)),
      "no native snipeit_session may be minted from a forged header",
    ).toBe(false);
  } finally {
    await context.close();
  }
});

test("oidc-security: a forged identity header cannot reach an authenticated Snipe-IT page", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "SNIPE_IT_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: FORGED_IDENTITY_HEADERS,
  });
  try {
    const response = await context.request.get(`${expectedBase}/account/profile`, {
      maxRedirects: 0,
    });
    expect(
      response.status(),
      `the auth-only profile page must redirect a forged-header request to /login, never serve 200 (got ${response.status()})`,
    ).not.toBe(200);
    const location = response.headers()["location"] || "";
    expect(
      /\/login/.test(location) || response.status() === 401 || response.status() === 403,
      `an unauthenticated forged-header request must be sent to /login (got status ${response.status()}, location "${location}")`,
    ).toBe(true);
  } finally {
    await context.close();
  }
});

test("oidc-security: the trusted-header bridge stays inert while SSO is disabled", async ({ browser }) => {
  test.skip(isServiceEnabled("sso"), "SSO enabled — forged-header gating is covered by the tests above");
  expect(baseUrl, "SNIPE_IT_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: FORGED_IDENTITY_HEADERS,
  });
  try {
    const response = await context.request.get(`${expectedBase}/account/profile`, {
      maxRedirects: 0,
    });
    expect(
      response.status(),
      `the bridge must be off while SSO is disabled: a forged header must never mint an authenticated session (got ${response.status()})`,
    ).not.toBe(200);
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
  await page.goto(`${expectedBase}/login`);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect
    .poll(() => page.url(), { timeout: 90_000, message: `expected redirect back to ${expectedBase}` })
    .toContain(expectedBase.replace(/^https?:\/\//, ""));

  const genuineProfile = await page.request.get(`${expectedBase}/account/profile`, {
    maxRedirects: 0,
  });
  expect(
    genuineProfile.status(),
    "the genuine oauth2 session must reach the authenticated profile before the injection probe",
  ).toBe(200);

  const forgedMarker = "forgedescalationprobe";
  const probed = await page.request.get(`${expectedBase}/account/profile`, {
    maxRedirects: 0,
    headers: {
      "X-Forwarded-Preferred-Username": forgedMarker,
      "X-Forwarded-User": forgedMarker,
      "X-Forwarded-Email": `${forgedMarker}@attacker.invalid`,
      "X-Auth-Request-Preferred-Username": forgedMarker,
      "X-Auth-Request-User": forgedMarker,
      "X-Auth-Request-Email": `${forgedMarker}@attacker.invalid`,
      "Remote-User": forgedMarker,
    },
  });
  const probedBody = await probed.text();
  expect(
    probed.status(),
    "the genuine session must survive the injection probe (cookie-based auth, not header-based)",
  ).toBe(200);
  expect(
    probedBody.toLowerCase(),
    "an injected header must not switch the established Snipe-IT session to the forged identity",
  ).not.toContain(forgedMarker);
});
