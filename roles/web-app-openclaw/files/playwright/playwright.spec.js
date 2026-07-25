const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({
  ignoreHTTPSErrors: true,
});

test.beforeEach(shared.beforeEach);

require("./test-guest").register(shared);
require("./test-administrator-persona").register(shared);
require("./test-oidc-login");
