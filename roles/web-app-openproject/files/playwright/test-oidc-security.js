const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled, isServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.OPENPROJECT_BASE_URL || process.env.APP_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

const FORGED_IDENTITY_HEADERS = {
  "X-Forwarded-Preferred-Username": "administrator",
  "X-Forwarded-User": "administrator",
  "X-Forwarded-Email": "administrator@example.com",
  "X-Forwarded-Groups": "/roles/web-app-openproject/administrator",
  "X-Remote-User": "administrator",
};

test.use({ ignoreHTTPSErrors: true });

test("oidc-security: a forged identity header cannot bypass the oauth2-proxy gate", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "OPENPROJECT_BASE_URL must be set").toBeTruthy();

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
        message: "a forged identity header must be bounced to Keycloak, never into OpenProject",
      })
      .toContain("openid-connect/auth");

    const sessionCookies = await context.cookies(expectedBase);
    expect(
      sessionCookies.some((cookie) => cookie.name === "_open_project_session"),
      "no OpenProject session cookie may be minted from a forged header",
    ).toBe(false);
  } finally {
    await context.close();
  }
});

test("oidc-security: a forged identity header cannot authenticate through the trusted-header bridge", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "OPENPROJECT_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: FORGED_IDENTITY_HEADERS,
  });
  try {
    const response = await context.request.get(`${expectedBase}/api/v3/users/me`, {
      headers: { Accept: "application/hal+json" },
    });
    const body = await response.text();

    let resolvedLogin = null;
    try {
      const parsed = JSON.parse(body);
      resolvedLogin = parsed._type === "User" ? String(parsed.login || "") : null;
    } catch {
      resolvedLogin = null;
    }

    expect(
      resolvedLogin,
      `the trusted-header bridge must never authenticate an un-proxied request (got ${response.status()}: ${body.slice(0, 200)})`,
    ).toBeFalsy();
    expect(
      response.url(),
      "the bridge surface must sit behind the oauth2-proxy gate",
    ).toContain("openid-connect/auth");
  } finally {
    await context.close();
  }
});

test("oidc-security: the trusted-header bridge stays inert while SSO is disabled", async ({ browser }) => {
  test.skip(isServiceEnabled("sso"), "SSO enabled — forged-header gating is covered by the tests above");
  expect(baseUrl, "OPENPROJECT_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: FORGED_IDENTITY_HEADERS,
  });
  try {
    const response = await context.request.get(`${expectedBase}/api/v3/users/me`, {
      headers: { Accept: "application/hal+json" },
    });
    const body = await response.text();

    let resolvedLogin = null;
    try {
      const parsed = JSON.parse(body);
      resolvedLogin = parsed._type === "User" ? String(parsed.login || "") : null;
    } catch {
      resolvedLogin = null;
    }

    expect(
      resolvedLogin,
      `a forged identity header must never authenticate an OpenProject session while SSO is disabled (got ${response.status()}: ${body.slice(0, 200)})`,
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
  const response = await page.request.get(`${expectedBase}/api/v3/users/me`, {
    headers: {
      Accept: "application/hal+json",
      "X-Forwarded-Email": `${forgedMarker}@attacker.invalid`,
      "X-Forwarded-Preferred-Username": forgedMarker,
      "X-Forwarded-User": forgedMarker,
      "X-Forwarded-Groups": "/roles/web-app-openproject/administrator",
      "X-Remote-User": `${forgedMarker}:bogussecret`,
      "X-Auth-Request-Preferred-Username": forgedMarker,
      "X-Auth-Request-User": forgedMarker,
      "Remote-User": forgedMarker,
    },
  });
  const body = await response.text();
  expect(
    response.ok(),
    `the bridge must still authenticate the genuine proxied session (got ${response.status()}: ${body.slice(0, 200)})`,
  ).toBe(true);

  const me = JSON.parse(body);
  const resolvedIdentity = `${me.login || ""} ${me.email || ""}`.toLowerCase();
  expect(
    resolvedIdentity,
    `the oauth2-proxy identity must win over injected headers (resolved: ${resolvedIdentity})`,
  ).not.toContain(forgedMarker);
  expect(
    String(me.login || "").toLowerCase(),
    "the genuine Keycloak identity must remain the authenticated OpenProject login",
  ).toBe(adminUsername.toLowerCase());
});
