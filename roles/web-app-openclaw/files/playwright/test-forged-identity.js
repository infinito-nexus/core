const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  HEALTHZ_PATHS,
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  parseStrictBoolean,
  probeForgedIdentity,
} = require("./personas");

const baseUrl = normalizeBaseUrl(decodeDotenvQuotedValue(process.env.OPENCLAW_BASE_URL || ""));
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");

test.use({ ignoreHTTPSErrors: true });

test("forged-identity: forged identity headers open no OpenClaw session on any probed path", async ({ request }) => {
  test.setTimeout(resolveTimeout(180_000));
  expect(baseUrl, "OPENCLAW_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  const prometheusIntegration = parseStrictBoolean(
    process.env.PROMETHEUS_INTEGRATION_ACTIVE,
    "PROMETHEUS_INTEGRATION_ACTIVE",
  );

  const results = await probeForgedIdentity(request, {
    baseUrl,
    paths: ["/"],
    identity: {
      username: adminUsername,
      email: adminEmail,
      groups: "/roles/web-app-openclaw/administrator",
    },
    prometheusIntegration,
  });
  for (const result of results) {
    if (!HEALTHZ_PATHS.includes(result.path)) {
      expect(
        result.status,
        `${result.path}: the gate must not serve OpenClaw to a forged identity (location "${result.location}")`,
      ).not.toBe(200);
    }
    expect(
      result.body,
      `${result.path}: a forged identity must not be echoed as the signed-in administrator (status ${result.status})`,
    ).not.toContain(adminEmail);
  }
});
