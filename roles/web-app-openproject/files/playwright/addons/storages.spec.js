const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { normalizeBaseUrl, runAdminFlow } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const nextcloudBaseUrl = normalizeBaseUrl(process.env.NEXTCLOUD_BASE_URL || "");

test("addon storages: the partner Nextcloud is registered as a file storage", async ({ page }) => {
  skipUnlessAddonEnabled("storages");
  test.setTimeout(resolveTimeout(240_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(nextcloudBaseUrl, "NEXTCLOUD_BASE_URL must be set to address the partner").toBeTruthy();

  await runAdminFlow(page);

  const response = await page.request.get(`${appBaseUrl}/api/v3/storages`, {
    headers: { Accept: "application/json" },
    failOnStatusCode: false,
    maxRedirects: 0,
    timeout: resolveTimeout(60_000),
  });

  expect(
    response.status(),
    "the storages collection must be served; a 404 means the module is not loaded in this OpenProject build, a 302 that runAdminFlow left no session and OpenProject is redirecting to its login. This status alone proves nothing about the session - the endpoint answers 200 with an empty collection for an anonymous caller too, which is why the count below is the real assertion",
  ).toBe(200);

  expect(
    response.headers()["content-type"] || "",
    "the collection must come back as JSON; an HTML body means OpenProject served its login page under 200, so runAdminFlow established no session and every assertion below would read an empty page rather than a storage",
  ).toContain("json");

  const body = await response.json();
  expect(
    Number(body.total || 0),
    "web-app-nextcloud provisions the storage into this OpenProject through rails runner; zero storages means that provisioning never ran or silently failed, and the Nextcloud side is then pointing at nothing",
  ).toBeGreaterThanOrEqual(1);

  const host = nextcloudBaseUrl.replace(/^https?:\/\//, "").replace(/\/$/, "");
  expect(
    JSON.stringify(body).includes(host),
    `a storage exists but none of them addresses the partner ${host}; the registered storage points somewhere else, so files attached in OpenProject never reach this deployment's Nextcloud`,
  ).toBe(true);
});
