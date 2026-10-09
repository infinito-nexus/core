const { test, expect } = require("@playwright/test");
const { runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async () => {
  expect(shared.appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(shared.canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  expect(shared.translatedRole, "TRANSLATED_ROLE must be set").toBeTruthy();
});

require("./test-health").register(shared);
require("./test-repository").register(shared);
require("./test-roles").register(shared);
require("./test-i18n").register(shared);
require("./test-files").register(shared);

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page);
});
