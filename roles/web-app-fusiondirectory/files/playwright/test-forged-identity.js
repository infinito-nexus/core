const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl, decodeDotenvQuotedValue, parseStrictBoolean, probeForgedIdentity } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.FUSIONDIRECTORY_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");
const adminGroup = decodeDotenvQuotedValue(process.env.RBAC_ADMINISTRATOR_GROUP_PATH || "");

const PROBE_PATHS = ["/", "/index.php", "/main.php"];

test.use({ ignoreHTTPSErrors: true });

test("forged-identity: forged administrator headers open no FusionDirectory session", async ({ request }) => {
  expect(baseUrl, "FUSIONDIRECTORY_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  expect(adminGroup, "RBAC_ADMINISTRATOR_GROUP_PATH must be set").toBeTruthy();
  const prometheusIntegration = parseStrictBoolean(
    process.env.PROMETHEUS_INTEGRATION_ACTIVE,
    "PROMETHEUS_INTEGRATION_ACTIVE",
  );

  const results = await probeForgedIdentity(request, {
    baseUrl,
    paths: PROBE_PATHS,
    identity: { username: adminUsername, email: adminEmail, groups: adminGroup },
    prometheusIntegration,
  });

  for (const result of results) {
    expect(
      result.body,
      `${result.path} answered ${result.status}: a plugin window proves a FusionDirectory session opened by the header login`,
    ).not.toContain("plugin-window");
  }
});
