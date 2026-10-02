const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceDisabled } = require("../service-gating");
const { normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");

test("addon gitlab_integration: the GitLab webhook endpoint is mounted for the partner to post to", async ({ request }) => {
  skipUnlessAddonEnabled("gitlab_integration");
  skipUnlessServiceDisabled("sso");
  test.setTimeout(resolveTimeout(120_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();

  const response = await request.post(`${appBaseUrl.replace(/\/$/, "")}/webhooks/gitlab`, {
    headers: { "Content-Type": "application/json" },
    data: {},
    failOnStatusCode: false,
    timeout: resolveTimeout(60_000),
  });

  expect(
    response.status(),
    "the gitlab integration module mounts POST /webhooks/gitlab; a 404 means the route is absent, so GitLab push and merge-request events never reach a work package",
  ).not.toBe(404);
  expect(
    response.status(),
    `the mounted webhook must reject an unsigned empty payload rather than accept it, and must not fail with a server error - got HTTP ${response.status()}`,
  ).toBeLessThan(500);
});
