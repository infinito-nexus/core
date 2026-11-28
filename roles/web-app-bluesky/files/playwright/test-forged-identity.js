const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue, parseStrictBoolean, probeForgedIdentity } = require("./personas");

const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");

const ADMIN_GROUP = "/roles/web-app-bluesky/administrator";
const PROBE_PATHS = ["/", "/settings"];
const HANDOFF_COOKIE = "bsky_handoff_done";
const HANDOFF_MARKERS = [/Signing you in to Bluesky/, /localStorage\.setItem\("BSKY_STORAGE"/, /"accessJwt"\s*:\s*"/];
const SESSION_TOKEN_IN_LOCATION = /accessJwt|refreshJwt/i;

exports.register = function (shared) {
  test("forged-identity: forged administrator headers get no login-broker handoff", async ({ request }) => {
    const { baseUrl, adminUsername } = shared.env;
    expect(baseUrl, "BLUESKY_BASE_URL must be set").toBeTruthy();
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
        `${label}: a forged header must not set the broker's ${HANDOFF_COOKIE} cookie`,
      ).not.toContain(HANDOFF_COOKIE);
      expect(
        result.location,
        `${label}: a forged header must not be redirected with a PDS session token (Location: ${result.location})`,
      ).not.toMatch(SESSION_TOKEN_IN_LOCATION);
      for (const marker of HANDOFF_MARKERS) {
        expect(
          result.body,
          `${label}: the login broker must not render a PDS session handoff for a forged header`,
        ).not.toMatch(marker);
      }
    }
  });
};
