const { test, expect } = require("@playwright/test");

const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async ({ page }) => {
  expect(shared.env.appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(shared.env.canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

require("./test-editor-front-page").register(shared);
require("./test-renders-require-login").register(shared);
require("./test-guest-persona").register(shared);
require("./test-biber-persona").register(shared);
