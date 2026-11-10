// /healthz/ready on the Gitea domain returns a non-5xx response.
//
// This is the endpoint the Blackbox Exporter probes to determine whether
// Gitea is up. A 200 or 401 means the backend is reachable; 502/503 means
// the container is down. This test verifies the healthz endpoint is wired
// correctly.

const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue } = require("./personas");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("healthz/ready endpoint returns non-5xx when gitea is running", async ({ request }) => {
    const response = await request.get(shared.healthzReadyUrl(), { timeout: resolveTimeout(30_000) });

    expect(
      response.status(),
      `/healthz/ready returned ${response.status()} — ` +
      "502/503 means the Gitea container is down or nginx cannot reach it.",
    ).toBeLessThan(500);
  });

  test("the running gitea is the version the role pins", async ({ request }) => {
    const response = await request.get(`${shared.env.gitEaBaseUrl.replace(/\/$/, "")}/api/v1/version`, {
      timeout: resolveTimeout(30_000),
    });
    expect(response.ok(), `/api/v1/version returned ${response.status()}`).toBe(true);
    expect(
      (await response.json()).version,
      "a redeploy must replace a container that still runs an older image",
    ).toBe(decodeDotenvQuotedValue(process.env.GITEA_VERSION));
  });
};
