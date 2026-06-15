const { test } = require("@playwright/test");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async ({ context }) => {
  await context.clearCookies();
});

require("./test-administrator-persona").register(shared);
require("./test-biber-persona").register(shared);
require("./test-guest-persona").register(shared);
require("./test-storage-buckets").register(shared);
