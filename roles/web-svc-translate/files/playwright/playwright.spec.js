const { test, expect } = require("@playwright/test");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async () => {
  expect(shared.appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(shared.canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  expect(shared.engines.length, "TRANSLATE_ENGINES must name at least one backend").toBeGreaterThan(0);
});

require("./test-api").register(shared);
require("./test-weblate").register(shared);
