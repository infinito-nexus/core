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
require("./test-publish-mastodon").register(shared);
require("./test-publish-pixelfed").register(shared);
require("./test-crossposter-draft").register(shared);
require("./test-crossposter-linkedin").register(shared);
require("./test-seaweedfs").register(shared);
