const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  gotoOnion,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.LITELLM_UI_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");

/**
 * Args:
 *   page: page whose context holds the LiteLLM UI session after the SSO callback.
 *   uiHost: hostname the UI is served on.
 * Returns: the claims of the session token LiteLLM sets for its UI.
 */
async function uiSessionClaims(page, uiHost) {
  const cookie = (await page.context().cookies()).find((c) => c.name === "token" && uiHost.endsWith(c.domain.replace(/^\./, "")));
  expect(cookie, "the SSO callback MUST set the LiteLLM UI session token cookie").toBeTruthy();
  const payload = cookie.value.split(".")[1] || "";
  return JSON.parse(Buffer.from(payload.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8"));
}

test.use({ ignoreHTTPSErrors: true });

test("OIDC: the LiteLLM admin UI signs the administrator in through Keycloak", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "LITELLM_UI_BASE_URL must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  await page.context().clearCookies();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await gotoOnion(page, `${expectedBase}/sso/key/generate`);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected /sso/key/generate to redirect to ${expectedAuth}; staying put means GENERIC_CLIENT_ID never reached the gateway`,
    })
    .toContain(expectedAuth);

  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(90_000),
      message: `expected Keycloak to redirect back to ${expectedBase}`,
    })
    .toContain(expectedBase);

  const claims = await uiSessionClaims(page, new URL(expectedBase).hostname);
  expect(claims.user_id, "GENERIC_USER_ID_ATTRIBUTE MUST name the LiteLLM user after the OIDC username claim").toBe(adminUsername);
  expect(claims.user_email, "GENERIC_USER_EMAIL_ATTRIBUTE MUST carry the OIDC email claim").toBe(adminEmail);
  expect(claims.user_role, "PROXY_ADMIN_ID MUST match the mapped user id and grant proxy_admin").toBe("proxy_admin");

  await gotoOnion(page, `${expectedBase}/ui`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator("input[type=password]"),
    "after the Keycloak round-trip the UI must not fall back to its own username/password gate",
  ).toHaveCount(0, { timeout: resolveTimeout(30_000) });
});
