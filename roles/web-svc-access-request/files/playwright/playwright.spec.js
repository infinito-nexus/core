const { test, expect } = require("@playwright/test");
const { runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async () => {
  expect(shared.env.appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(shared.env.canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
});

require("./test-request-flow").register(shared);
require("./test-delegation").register(shared);
require("./test-forged-identity");

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page);
});
