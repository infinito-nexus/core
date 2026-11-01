const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  apiGetOnion,
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  parseStrictBoolean,
  probeForgedIdentity,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.SNIPE_IT_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");

const PROFILE_PATH = "/account/profile";
const AUTH_ONLY_PATHS = ["/", PROFILE_PATH, "/admin"];
const ANONYMOUS_LOCATION = /\/login(\?|$)|\/oauth2\/|openid-connect\/auth/;

test.use({ ignoreHTTPSErrors: true });

test("forged-identity: forged identity headers open no Snipe-IT session on any probed path", async ({ request }) => {
  test.setTimeout(resolveTimeout(180_000));
  expect(baseUrl, "SNIPE_IT_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  const prometheusIntegration = parseStrictBoolean(
    process.env.PROMETHEUS_INTEGRATION_ACTIVE,
    "PROMETHEUS_INTEGRATION_ACTIVE",
  );

  const results = await probeForgedIdentity(request, {
    baseUrl,
    paths: ["/login", ...AUTH_ONLY_PATHS],
    identity: {
      username: adminUsername,
      email: adminEmail,
      groups: "/roles/web-app-snipe-it/administrator",
    },
    prometheusIntegration,
  });
  for (const result of results) {
    if (result.location) {
      expect(
        result.location,
        `${result.path}: a forged request may only be sent to /login or Keycloak, never into Snipe-IT (status ${result.status})`,
      ).toMatch(ANONYMOUS_LOCATION);
    }
    if (AUTH_ONLY_PATHS.includes(result.path)) {
      expect(
        result.status,
        `${result.path}: an auth-only page must not render for a forged identity (location "${result.location}")`,
      ).not.toBe(200);
    }
  }

  const profile = await apiGetOnion(request, `${baseUrl}${PROFILE_PATH}`, {
    maxRedirects: 0,
    failOnStatusCode: false,
    ignoreHTTPSErrors: true,
    timeout: resolveTimeout(30_000),
  });
  expect(
    profile.status(),
    `no forged probe may leave a logged-in snipeit_session in the request context (location "${profile.headers().location || ""}")`,
  ).not.toBe(200);
});
