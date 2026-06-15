// Taiga Playwright spec — orchestration only. Shared state, locator
// helpers, and the login/logout flow live in `_shared.js`; each scenario
// is registered from its own `test-*.js` companion module so each test
// stays atomar and individually inspectable.

const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({
  ignoreHTTPSErrors: true,
});

test.beforeEach(shared.beforeEach);

require("./test-login-oidc").register(shared);
require("./test-login-native").register(shared);
require("./test-public-discover-themed-surface").register(shared);
require("./test-public-discover-hides-local-login").register(shared);
require("./test-themed-routes").register(shared);
require("./test-guest-persona").register(shared);
require("./test-biber-persona").register(shared);
require("./test-administrator-persona").register(shared);
require("./test-seaweedfs");
