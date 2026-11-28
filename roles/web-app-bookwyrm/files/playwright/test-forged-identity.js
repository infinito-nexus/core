const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  apiGetOnion,
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  parseStrictBoolean,
  probeForgedIdentity,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.BOOKWYRM_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");

const SESSION_COOKIE = "sessionid";
const ADMIN_GROUP = "/roles/web-app-bookwyrm/administrator";
const PROFILE_PATH = "/preferences/profile";
const AUTHENTICATED_MARKER = 'name="edit-profile"';

function expectNoProfileSurface(label, status, body) {
  expect(
    status >= 200 && status < 300 && body.includes(AUTHENTICATED_MARKER),
    `${label}: the logged-in profile form must not be served to a forged identity (got ${status})`,
  ).toBe(false);
}

test.use({ ignoreHTTPSErrors: true });

test("forged-identity: forged identity headers open no BookWyrm session on any probed path", async ({ request }) => {
  expect(baseUrl, "BOOKWYRM_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  const prometheusIntegration = parseStrictBoolean(
    process.env.PROMETHEUS_INTEGRATION_ACTIVE,
    "PROMETHEUS_INTEGRATION_ACTIVE",
  );

  const results = await probeForgedIdentity(request, {
    baseUrl,
    paths: ["/", PROFILE_PATH],
    identity: { username: adminUsername, email: adminEmail, groups: ADMIN_GROUP },
    prometheusIntegration,
  });

  for (const result of results) {
    expect(
      result.setCookieNames,
      `${result.path}: a forged identity must not log anyone in, so Django must not issue ${SESSION_COOKIE}`,
    ).not.toContain(SESSION_COOKIE);
    expect(
      result.body,
      `${result.path}: a forged identity must not be served the logged-in profile form`,
    ).not.toContain(AUTHENTICATED_MARKER);
  }

  const profile = results.find((result) => result.path === PROFILE_PATH);
  expect(
    profile.status >= 200 && profile.status < 300,
    `forged ${PROFILE_PATH}: a login-only page must not answer 2xx to a forged identity (got ${profile.status})`,
  ).toBe(false);

  const replay = await apiGetOnion(request, `${baseUrl}${PROFILE_PATH}`, {
    maxRedirects: 0,
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expectNoProfileSurface(
    `cookies collected by the forged requests, replayed on ${PROFILE_PATH}`,
    replay.status(),
    await replay.text(),
  );
});
