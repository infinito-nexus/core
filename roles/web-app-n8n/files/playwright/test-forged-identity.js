const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { apiGetOnion, parseStrictBoolean, probeForgedIdentity } = require("./personas");

const SESSION_COOKIE = "n8n-auth";
const ADMIN_GROUP = "/roles/web-app-n8n/administrator";
const CURRENT_USER_PATH = "/rest/login";

exports.register = function (shared) {
  test("forged-identity: forged identity headers mint no n8n session on any probed path", async ({ request }) => {
    expect(shared.env.n8nBaseUrl, "N8N_BASE_URL must be set").toBeTruthy();
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
    const prometheusIntegration = parseStrictBoolean(
      process.env.PROMETHEUS_INTEGRATION_ACTIVE,
      "PROMETHEUS_INTEGRATION_ACTIVE",
    );
    const adminEmail = shared.env.adminEmail.toLowerCase();

    const results = await probeForgedIdentity(request, {
      baseUrl: shared.env.n8nBaseUrl,
      paths: ["/", CURRENT_USER_PATH],
      identity: { username: shared.env.adminUsername, email: shared.env.adminEmail, groups: ADMIN_GROUP },
      prometheusIntegration,
    });

    for (const result of results) {
      expect(
        result.setCookieNames,
        `${result.path}: a forged Remote-Email must not make hooks.js issue ${SESSION_COOKIE}`,
      ).not.toContain(SESSION_COOKIE);
      expect(
        result.body.toLowerCase(),
        `${result.path}: the administrator's account must not be returned to a forged identity`,
      ).not.toContain(adminEmail);
    }

    const currentUser = results.find((result) => result.path === CURRENT_USER_PATH);
    expect(
      currentUser.status,
      `forged ${CURRENT_USER_PATH}: n8n must not report an authenticated user (got ${currentUser.status})`,
    ).not.toBe(200);

    const replay = await apiGetOnion(request, `${shared.env.n8nBaseUrl}${CURRENT_USER_PATH}`, {
      maxRedirects: 0,
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
    expect(
      replay.status(),
      `cookies collected by the forged requests, replayed on ${CURRENT_USER_PATH}, must not authenticate (got ${replay.status()})`,
    ).not.toBe(200);
    expect(
      (await replay.text()).toLowerCase(),
      `cookies collected by the forged requests must not resolve to the administrator's account`,
    ).not.toContain(adminEmail);
  });
};
