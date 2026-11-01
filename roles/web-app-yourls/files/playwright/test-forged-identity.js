const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl, decodeDotenvQuotedValue, parseStrictBoolean, probeForgedIdentity } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.YOURLS_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");

const ADMIN_GROUP = "/roles/web-app-yourls/administrator";
const ADMIN_PATH_PREFIX = "/admin";
const PROBE_PATHS = ["/", "/admin/", "/admin/index.php", "/yourls-api.php?action=db-stats&format=json"];
const REDIRECTS_EVERY_VISITOR_TO_ADMIN = new Set(["/"]);

test.use({ ignoreHTTPSErrors: true });

function sameOriginAdminRedirect(result) {
  if (!result.location) return false;
  const target = new URL(result.location, result.url);
  return target.origin === new URL(result.url).origin && target.pathname.startsWith(ADMIN_PATH_PREFIX);
}

test("forged-identity: forged administrator headers open no YOURLS admin session", async ({ request }) => {
  expect(baseUrl, "YOURLS_BASE_URL must be set").toBeTruthy();
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
      result.setCookieNames.filter((name) => /^yourls_/i.test(name)),
      `${label}: a forged header must not mint a YOURLS auth cookie`,
    ).toEqual([]);
    expect(
      result.body,
      `${label}: the admin logout link proves an authenticated YOURLS admin page`,
    ).not.toContain("action=logout");
    expect(
      result.body,
      `${label}: db-stats data proves an authenticated YOURLS API call`,
    ).not.toContain('"total_links"');
    if (!REDIRECTS_EVERY_VISITOR_TO_ADMIN.has(result.path)) {
      expect(
        sameOriginAdminRedirect(result),
        `${label}: a forged header must not redirect into the YOURLS admin area (Location: ${result.location})`,
      ).toBe(false);
    }
  }
});
