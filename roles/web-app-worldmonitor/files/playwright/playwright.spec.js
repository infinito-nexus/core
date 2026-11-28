const { test, expect } = require("@playwright/test");

const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async ({ page }) => {
  expect(shared.env.appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(shared.env.canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

require("./test-guest").register(shared);
require("./test-oidc-login").register(shared);
require("./test-live-updates").register(shared);
require("./test-isolation").register(shared);
