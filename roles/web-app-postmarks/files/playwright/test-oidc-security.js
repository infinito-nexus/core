const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled, isServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.POSTMARKS_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

const FORGED_IDENTITY_HEADERS = {
  "X-Forwarded-Preferred-Username": "administrator",
  "X-Forwarded-User": "administrator",
  "X-Forwarded-Email": "administrator@example.com",
  "X-Forwarded-Groups": "/roles/web-app-postmarks/administrator",
};

test.use({ ignoreHTTPSErrors: true });

test("oidc-security: a forged identity header cannot bypass the oauth2-proxy gate", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "POSTMARKS_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: FORGED_IDENTITY_HEADERS,
  });
  try {
    const page = await context.newPage();
    await page.goto(`${expectedBase}/admin`, { waitUntil: "domcontentloaded" });

    // The browser never authenticated against oauth2-proxy, so even with a
    // fully forged identity header it must be bounced to Keycloak; nginx
    // overwrites X-Forwarded-* only after a real oauth2-proxy auth, so the
    // forged header never reaches Postmarks' middleware.
    await expect
      .poll(() => page.url(), {
        timeout: 60_000,
        message: "a forged identity header must be bounced to Keycloak, never into Postmarks /admin",
      })
      .toContain("openid-connect/auth");

    const sessionCookies = await context.cookies(expectedBase);
    expect(
      sessionCookies.some((cookie) => cookie.name === "connect.sid"),
      "no Postmarks owner session cookie may be minted from a forged header",
    ).toBe(false);
  } finally {
    await context.close();
  }
});

test("oidc-security: the trusted-header bridge stays inert while SSO is disabled", async ({ browser }) => {
  test.skip(isServiceEnabled("sso"), "SSO enabled — forged-header gating is covered by the tests above");
  expect(baseUrl, "POSTMARKS_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: FORGED_IDENTITY_HEADERS,
  });
  try {
    const page = await context.newPage();
    await page.goto(`${expectedBase}/admin`, { waitUntil: "domcontentloaded" });

    // With PROXY_HEADER_SSO unset the middleware is a pass-through, so a
    // forged header must never flip the owner session: the native gate
    // bounces the request to the password login form.
    expect(
      page.url(),
      `a forged header must not open /admin while SSO is disabled (at ${page.url()})`,
    ).not.toMatch(/\/admin(\/|$)/);
    expect(
      page.url(),
      `the native /login form must guard /admin while SSO is disabled (at ${page.url()})`,
    ).toMatch(/\/login(\?|$)/);
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

  // Establish the genuine owner session via the gated /admin path.
  await page.goto(`${expectedBase}/admin`, { waitUntil: "domcontentloaded" });
  expect(
    page.url(),
    `the genuine proxied session must open /admin (at ${page.url()})`,
  ).not.toMatch(/\/login(\?|$)/);

  // Postmarks has no per-user identity to escalate — the only authorization
  // tier is the single owner boolean. Injecting forged X-Forwarded-* /
  // X-Auth-Request-* / Remote-User headers on a request inside the genuine
  // session must neither break nor re-scope it: nginx overwrites the trusted
  // X-Forwarded-* and the middleware ignores the Remote-User / X-Auth-Request
  // variants entirely.
  const forgedMarker = "forgedescalationprobe";
  const response = await page.request.get(`${expectedBase}/admin`, {
    headers: {
      "X-Forwarded-Email": `${forgedMarker}@attacker.invalid`,
      "X-Forwarded-Preferred-Username": forgedMarker,
      "X-Forwarded-User": forgedMarker,
      "X-Forwarded-Groups": "/roles/web-app-postmarks/administrator",
      "X-Auth-Request-Email": `${forgedMarker}@attacker.invalid`,
      "X-Auth-Request-Preferred-Username": forgedMarker,
      "X-Auth-Request-User": forgedMarker,
      "Remote-User": forgedMarker,
    },
  });
  const body = await response.text();
  expect(
    response.ok(),
    `the genuine owner session must still reach /admin (got ${response.status()}: ${body.slice(0, 200)})`,
  ).toBe(true);
  expect(
    response.url(),
    `the genuine session must not be bounced to /login by injected headers (at ${response.url()})`,
  ).not.toMatch(/\/login(\?|$)/);
  expect(
    body.toLowerCase(),
    `injected attacker identity must never surface in the authenticated response (marker: ${forgedMarker})`,
  ).not.toContain(forgedMarker);
});
