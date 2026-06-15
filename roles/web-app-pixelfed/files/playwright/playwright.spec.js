// Pixelfed Playwright spec — orchestration only. Shared state, locator
// helpers, and the Keycloak email-swap setup live in `_shared.js`; each
// scenario is registered from its own `test-*.js` companion module so
// each test stays atomar and individually inspectable.

const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({
  ignoreHTTPSErrors: true,
});

test.beforeAll(shared.beforeAll);

test.afterAll(shared.afterAll);

test.beforeEach(shared.beforeEach);

require("./test-oidc-login-biber").register(shared);
require("./test-oidc-login-administrator").register(shared);
require("./test-native-login-administrator").register(shared);
require("./test-guest-persona").register(shared);
require("./test-biber-persona").register(shared);
require("./test-administrator-persona").register(shared);
require("./test-seaweedfs");
