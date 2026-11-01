const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl, decodeDotenvQuotedValue, parseStrictBoolean, probeForgedIdentity } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.BASEROW_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");

const ADMIN_GROUP = "/roles/web-app-baserow/administrator";
const PROBE_PATHS = ["/", "/api/infinito/sso/login/", "/api/infinito/sso/token/"];
const SESSION_COOKIE = "jwt_token";
const HANDOFF_QUERY = /[?&](?:token|user_session)=/;
const TOKEN_PAYLOAD = /"(?:access_token|refresh_token|user_session)"\s*:/;

test.use({ ignoreHTTPSErrors: true });

test("forged-identity: forged administrator headers mint no Baserow session", async ({ request }) => {
  expect(baseUrl, "BASEROW_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  const prometheusIntegration = parseStrictBoolean(
    process.env.PROMETHEUS_INTEGRATION_ACTIVE,
    "PROMETHEUS_INTEGRATION_ACTIVE",
  );

  const results = await probeForgedIdentity(request, {
    baseUrl,
    paths: PROBE_PATHS,
    identity: { username: adminUsername, email: adminEmail, groups: ADMIN_GROUP },
    prometheusIntegration,
  });

  for (const result of results) {
    const label = `${result.path} answered ${result.status}`;
    expect(
      result.setCookieNames,
      `${label}: a forged header must not set the Baserow ${SESSION_COOKIE} session cookie`,
    ).not.toContain(SESSION_COOKIE);
    expect(
      result.location,
      `${label}: the SSO login handoff must not hand a refresh token or user session to a forged header (Location: ${result.location})`,
    ).not.toMatch(HANDOFF_QUERY);
    expect(
      result.body,
      `${label}: the SSO token endpoint must not return a login payload for a forged header (${result.body.slice(0, 200)})`,
    ).not.toMatch(TOKEN_PAYLOAD);
  }
});
