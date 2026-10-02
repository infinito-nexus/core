const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");

test("addon storages: the file-storages module mounts its API so a Nextcloud storage can be registered", async ({ request }) => {
  skipUnlessAddonEnabled("storages");
  test.setTimeout(resolveTimeout(120_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();

  const response = await request.get(`${appBaseUrl.replace(/\/$/, "")}/api/v3/storages`, {
    headers: { Accept: "application/json" },
    failOnStatusCode: false,
    timeout: resolveTimeout(60_000),
  });

  expect(
    response.status(),
    "the storages module mounts /api/v3/storages; a 404 means the module is not loaded in this OpenProject build, so no Nextcloud file storage can be attached to a project at all",
  ).not.toBe(404);
  expect(
    [200, 401, 403],
    `an anonymous request must be answered by the mounted collection endpoint - served, or refused for lack of a session - got HTTP ${response.status()}`,
  ).toContain(response.status());
});
