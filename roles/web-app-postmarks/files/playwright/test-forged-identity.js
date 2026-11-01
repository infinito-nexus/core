const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  apiGetOnion,
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  parseStrictBoolean,
  probeForgedIdentity,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.POSTMARKS_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");

const SESSION_COOKIE = "connect.sid";
const ADMIN_GROUP = "/roles/web-app-postmarks/administrator";
const ADMIN_LOCATION = /^(?:https?:\/\/[^/]+)?\/admin(?:[/?#]|$)/;

function expectNoOwnerSurface(label, status, location) {
  expect(
    status >= 200 && status < 300,
    `${label}: /admin must not be served to a forged identity (got ${status})`,
  ).toBe(false);
  expect(location, `${label}: must not redirect into the owner area (Location: ${location})`).not.toMatch(ADMIN_LOCATION);
}

test.use({ ignoreHTTPSErrors: true });

test("forged-identity: forged identity headers mint no Postmarks owner session on any probed path", async ({ request }) => {
  expect(baseUrl, "POSTMARKS_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  const prometheusIntegration = parseStrictBoolean(
    process.env.PROMETHEUS_INTEGRATION_ACTIVE,
    "PROMETHEUS_INTEGRATION_ACTIVE",
  );

  const results = await probeForgedIdentity(request, {
    baseUrl,
    paths: ["/", "/admin"],
    identity: { username: adminUsername, email: adminEmail, groups: ADMIN_GROUP },
    prometheusIntegration,
  });

  for (const result of results) {
    expect(
      result.setCookieNames,
      `${result.path}: a forged identity must not mint the Postmarks owner session cookie ${SESSION_COOKIE}`,
    ).not.toContain(SESSION_COOKIE);
  }

  const admin = results.find((result) => result.path === "/admin");
  expectNoOwnerSurface("forged /admin", admin.status, admin.location);

  const replay = await apiGetOnion(request, `${baseUrl}/admin`, {
    maxRedirects: 0,
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expectNoOwnerSurface("cookies collected by the forged requests, replayed on /admin", replay.status(), replay.headers().location || "");
});
