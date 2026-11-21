const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  apiGetOnion,
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  parseStrictBoolean,
  probeForgedIdentity,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.OPENPROJECT_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");

const ME_PATH = "/api/v3/users/me";
const LOGIN_ONLY_PATHS = ["/my/page", "/admin"];
const AUTHENTICATED_LOCATION = /^\/(my|admin)(\/|$)/;

function resolvedLoginOf(body) {
  try {
    const parsed = JSON.parse(body);
    return parsed._type === "User" ? String(parsed.login || "").toLowerCase() : "";
  } catch {
    return "";
  }
}

function locationPathOf(location) {
  return new URL(location, baseUrl).pathname;
}

test.use({ ignoreHTTPSErrors: true });

test("forged-identity: forged identity headers open no OpenProject session on any probed path", async ({ request }) => {
  test.setTimeout(resolveTimeout(180_000));
  expect(baseUrl, "OPENPROJECT_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  const prometheusIntegration = parseStrictBoolean(
    process.env.PROMETHEUS_INTEGRATION_ACTIVE,
    "PROMETHEUS_INTEGRATION_ACTIVE",
  );

  const results = await probeForgedIdentity(request, {
    baseUrl,
    paths: ["/", ...LOGIN_ONLY_PATHS, ME_PATH],
    identity: {
      username: adminUsername,
      email: adminEmail,
      groups: "/roles/web-app-openproject/administrator",
    },
    prometheusIntegration,
  });
  for (const result of results) {
    if (result.location) {
      expect(
        locationPathOf(result.location),
        `${result.path}: a forged request must not be redirected into My page or the admin area (location "${result.location}")`,
      ).not.toMatch(AUTHENTICATED_LOCATION);
    }
    if (LOGIN_ONLY_PATHS.includes(result.path)) {
      expect(
        result.status,
        `${result.path}: a login-only page must not render for a forged identity (location "${result.location}")`,
      ).not.toBe(200);
    }
    expect(
      resolvedLoginOf(result.body),
      `${result.path}: a forged X-Remote-User without the proxy secret must not resolve the administrator (status ${result.status})`,
    ).not.toBe(adminUsername.toLowerCase());
  }

  const me = await apiGetOnion(request, `${baseUrl}${ME_PATH}`, {
    headers: { Accept: "application/hal+json" },
    failOnStatusCode: false,
    ignoreHTTPSErrors: true,
    timeout: resolveTimeout(30_000),
  });
  const meBody = await me.text();
  expect(
    resolvedLoginOf(meBody),
    `no forged probe may leave an administrator session in the request context (got ${me.status()}: ${meBody.slice(0, 200)})`,
  ).not.toBe(adminUsername.toLowerCase());
});
