const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({
  ignoreHTTPSErrors: true,
});

test.beforeEach(shared.beforeEach);

require("./test-landing").register(shared);
require("./test-csp-headers").register(shared);
require("./test-login-native-administrator").register(shared);
require("./test-login-administrator").register(shared);
require("./test-login-biber").register(shared);
require("./test-guest-persona").register(shared);
require("./test-design").register(shared);
