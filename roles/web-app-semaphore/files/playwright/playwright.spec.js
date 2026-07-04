const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({
  ignoreHTTPSErrors: true,
});

test.beforeEach(shared.beforeEach);

require("./test-guest").register(shared);
require("./test-login-native-administrator").register(shared);
require("./test-login-oidc-administrator").register(shared);
require("./test-login-oidc-biber").register(shared);
require("./test-login-ldap-biber").register(shared);
