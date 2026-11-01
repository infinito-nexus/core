const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  apiGetOnion,
  decodeDotenvQuotedValue,
  forgedIdentityHeaders,
  normalizeBaseUrl,
  parseStrictBoolean,
  probeForgedIdentity,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.CHECKMK_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");
const checkmkSite = decodeDotenvQuotedValue(process.env.CHECKMK_SITE || "");

const ANONYMOUS_LANDING = /login\.py|openid-connect\/auth/;

test.use({ ignoreHTTPSErrors: true });

test("forged-identity: forged identity headers open no Checkmk session on any probed path", async ({ request }) => {
  test.setTimeout(resolveTimeout(180_000));
  expect(baseUrl, "CHECKMK_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
  expect(checkmkSite, "CHECKMK_SITE must be set").toBeTruthy();
  const prometheusIntegration = parseStrictBoolean(
    process.env.PROMETHEUS_INTEGRATION_ACTIVE,
    "PROMETHEUS_INTEGRATION_ACTIVE",
  );
  const identity = {
    username: adminUsername,
    email: adminEmail,
    groups: "/roles/web-app-checkmk/administrator",
  };
  const guiPath = `/${checkmkSite}/check_mk/`;

  const results = await probeForgedIdentity(request, {
    baseUrl,
    paths: ["/", guiPath, `${guiPath}index.py`],
    identity,
    prometheusIntegration,
  });
  for (const result of results) {
    expect(
      result.setCookieNames.filter((name) => name.startsWith("auth_")),
      `${result.path}: no Checkmk auth_<site> session cookie may be minted from a forged header (status ${result.status})`,
    ).toEqual([]);
  }

  for (const path of [guiPath, `${guiPath}index.py`]) {
    const response = await apiGetOnion(request, `${baseUrl}${path}`, {
      headers: forgedIdentityHeaders(identity),
      failOnStatusCode: false,
      ignoreHTTPSErrors: true,
      timeout: resolveTimeout(30_000),
    });
    expect(
      response.url(),
      `${path}: a forged X-Remote-User must end on the Checkmk login or Keycloak, never inside the GUI (status ${response.status()})`,
    ).toMatch(ANONYMOUS_LANDING);
  }

  const checkmkHost = new URL(baseUrl).hostname;
  const { cookies } = await request.storageState();
  expect(
    cookies
      .filter((cookie) => cookie.domain.replace(/^\./, "") === checkmkHost && cookie.name.startsWith("auth_"))
      .map((cookie) => cookie.name),
    "no forged probe may leave a Checkmk auth_<site> session cookie in the request context",
  ).toEqual([]);
});
