const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceDisabled } = require("../service-gating");
const { normalizeBaseUrl, requireDotenvValue, runAdminFlow } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");

test("addon gitlab_integration: the webhook endpoint is mounted for the partner to post to", async ({ request }) => {
  skipUnlessAddonEnabled("gitlab_integration");
  skipUnlessServiceDisabled("sso");
  test.setTimeout(resolveTimeout(120_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();

  const response = await request.post(`${appBaseUrl}/webhooks/gitlab`, {
    headers: {
      "Content-Type": "application/json",
      "X-Gitlab-Event": "Push Hook",
    },
    data: {},
    failOnStatusCode: false,
    timeout: resolveTimeout(60_000),
  });

  expect(
    response.status(),
    "the gitlab integration module mounts POST /webhooks/gitlab; a 404 means the route is absent, so GitLab push and merge-request events never reach a work package",
  ).not.toBe(404);
  expect(
    [401, 403],
    `the webhook carries no key= token here, so the mounted route must refuse it; anything else means the endpoint accepts unauthenticated callers - got HTTP ${response.status()}`,
  ).toContain(response.status());
});

test("addon gitlab_integration: the bot account the webhook authenticates as exists", async ({ page }) => {
  skipUnlessAddonEnabled("gitlab_integration");
  skipUnlessServiceDisabled("sso");
  test.setTimeout(resolveTimeout(240_000));

  const botUsername = requireDotenvValue(process.env.GITLAB_BOT_USERNAME, "GITLAB_BOT_USERNAME");
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();

  await runAdminFlow(page);

  const filters = JSON.stringify([{ login: { operator: "=", values: [botUsername] } }]);
  const response = await page.request.get(
    `${appBaseUrl}/api/v3/users?filters=${encodeURIComponent(filters)}`,
    {
      headers: { Accept: "application/json" },
      failOnStatusCode: false,
      timeout: resolveTimeout(60_000),
    },
  );

  expect(response.status(), "an administrator session must be served the users collection").toBe(200);

  const body = await response.json();
  expect(
    Number(body.total || 0),
    `tasks/addons/gitlab_integration.yml creates '${botUsername}' and mints the API token the webhook URL carries as key=. No such account means the hook never ran, so every event GitLab posts answers 403`,
  ).toBe(1);
});
