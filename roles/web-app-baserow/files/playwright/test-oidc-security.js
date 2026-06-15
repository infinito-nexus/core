const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled, isServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.BASEROW_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

const FORGED_IDENTITY_HEADERS = {
  "X-Forwarded-Preferred-Username": "administrator",
  "X-Forwarded-User": "administrator",
  "X-Forwarded-Email": "administrator@example.com",
  "X-Forwarded-Groups": "/roles/web-app-baserow/administrator",
};

test.use({ ignoreHTTPSErrors: true });

test("oidc-security: a forged identity header cannot bypass the oauth2-proxy gate", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "BASEROW_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: FORGED_IDENTITY_HEADERS,
  });
  try {
    const page = await context.newPage();
    await page.goto(`${expectedBase}/`, { waitUntil: "domcontentloaded" });

    await expect
      .poll(() => page.url(), {
        timeout: 60_000,
        message: "a forged identity header must be bounced to Keycloak, never into Baserow",
      })
      .toContain("openid-connect/auth");

    const sessionCookies = await context.cookies(expectedBase);
    expect(
      sessionCookies.some((cookie) => cookie.name === "jwt_token"),
      "no Baserow jwt_token session cookie may be minted from a forged header",
    ).toBe(false);
  } finally {
    await context.close();
  }
});

test("oidc-security: a forged identity header cannot mint a Baserow JWT through the trusted-header bridge", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "BASEROW_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: FORGED_IDENTITY_HEADERS,
  });
  try {
    const response = await context.request.get(`${expectedBase}/api/infinito/sso/token/`);
    const body = await response.text();

    let mintedAccessToken = null;
    try {
      mintedAccessToken = JSON.parse(body).access_token;
    } catch {
      mintedAccessToken = null;
    }

    expect(
      mintedAccessToken,
      `the trusted-header bridge must never mint a token for an un-proxied request (got ${response.status()}: ${body.slice(0, 200)})`,
    ).toBeFalsy();
    expect(
      response.url(),
      "the bridge token endpoint must sit behind the oauth2-proxy gate",
    ).toContain("openid-connect/auth");
  } finally {
    await context.close();
  }
});

test("oidc-security: the trusted-header bridge stays inert while SSO is disabled", async ({ browser }) => {
  test.skip(isServiceEnabled("sso"), "SSO enabled — forged-header gating is covered by the tests above");
  expect(baseUrl, "BASEROW_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: FORGED_IDENTITY_HEADERS,
  });
  try {
    const response = await context.request.get(`${expectedBase}/api/infinito/sso/token/`);
    const body = await response.text();

    let mintedAccessToken = null;
    try {
      mintedAccessToken = JSON.parse(body).access_token;
    } catch {
      mintedAccessToken = null;
    }

    expect(
      response.ok(),
      `the SSO bridge endpoint must not be mounted while SSO is disabled (got ${response.status()}: ${body.slice(0, 200)})`,
    ).toBe(false);
    expect(
      mintedAccessToken,
      "a forged identity header must never mint a Baserow token while SSO is disabled",
    ).toBeFalsy();
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

  const forgedMarker = "forgedescalationprobe";
  const response = await page.request.get(`${expectedBase}/api/infinito/sso/token/`, {
    headers: {
      "X-Forwarded-Email": `${forgedMarker}@attacker.invalid`,
      "X-Forwarded-Preferred-Username": forgedMarker,
      "X-Forwarded-User": forgedMarker,
      "X-Forwarded-Name": forgedMarker,
      "X-Forwarded-Groups": "/roles/web-app-baserow/administrator",
      "X-Auth-Request-Email": `${forgedMarker}@attacker.invalid`,
      "X-Auth-Request-Preferred-Username": forgedMarker,
      "X-Auth-Request-User": forgedMarker,
      "Remote-User": forgedMarker,
    },
  });
  const body = await response.text();
  expect(
    response.ok(),
    `the bridge must still mint a token for the genuine proxied session (got ${response.status()}: ${body.slice(0, 200)})`,
  ).toBe(true);

  const tokenData = JSON.parse(body);
  const resolvedIdentity = `${tokenData.user?.email || ""} ${tokenData.user?.username || ""}`.toLowerCase();
  expect(
    resolvedIdentity,
    `the oauth2-proxy identity must win over injected headers (resolved: ${resolvedIdentity})`,
  ).not.toContain(forgedMarker);
});
