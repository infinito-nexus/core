const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  apiFetchOnion,
  decodeDotenvQuotedValue,
  forgedIdentityHeaders,
  normalizeBaseUrl,
  parseStrictBoolean,
  probeForgedIdentity,
  requireDotenvValue,
} = require("./personas");

const END_USER = "end-user-support";

const baseUrl = normalizeBaseUrl(decodeDotenvQuotedValue(process.env.APP_BASE_URL || ""));
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");
const adminGroup = decodeDotenvQuotedValue(process.env.ASSISTANT_ADMIN_GROUP || "");
const askPath = `/${requireDotenvValue(process.env.ASSISTANT_PATH, "ASSISTANT_PATH").replace(/^\/+|\/+$/g, "")}/ask`;

test.use({ ignoreHTTPSErrors: true });

test("forged-identity: forged identity headers never earn the technical consultant", async ({ request }) => {
  test.setTimeout(resolveTimeout(180_000));
  expect(baseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  expect(adminGroup, "ASSISTANT_ADMIN_GROUP must be set").toBeTruthy();
  const identity = { username: adminUsername, email: adminEmail, groups: adminGroup };

  const results = await probeForgedIdentity(request, {
    baseUrl,
    paths: ["/"],
    identity,
    prometheusIntegration: parseStrictBoolean(
      process.env.PROMETHEUS_INTEGRATION_ACTIVE,
      "PROMETHEUS_INTEGRATION_ACTIVE",
    ),
  });
  for (const result of results) {
    expect(
      result.body,
      `${result.path}: a forged identity must not be greeted as the administrator (status ${result.status})`,
    ).not.toContain(adminEmail);
  }

  const response = await apiFetchOnion(request, `${baseUrl}${askPath}`, {
    method: "POST",
    headers: { ...forgedIdentityHeaders(identity), "Content-Type": "application/json" },
    data: { question: "How do I reset my password?" },
    maxRedirects: 0,
    failOnStatusCode: false,
    ignoreHTTPSErrors: true,
    timeout: resolveTimeout(120_000),
  });
  expect(response.status(), `${askPath}: the forged request must reach the assistant`).toBe(200);
  expect(
    (await response.json()).persona,
    `${askPath}: forged administrator headers must be blanked before the assistant picks a persona`,
  ).toBe(END_USER);
});
