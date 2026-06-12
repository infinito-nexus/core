// Nextcloud Playwright spec — orchestration only. Shared state, locator
// helpers, modal dismissal, the login/logout flow, and the Talk admin
// verification live in `_shared.js`; each scenario is registered from its
// own `test-*.js` companion module so each test stays atomar and
// individually inspectable.
//
// `ignoreHTTPSErrors` is needed because the local stack typically uses the
// self-signed CA set up by `make trust-ca`, which the Playwright container
// does not trust by default.

const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({
  ignoreHTTPSErrors: true,
});

test.beforeEach(shared.beforeEach);

require("./test-talk-admin-settings").register(shared);
require("./test-login-admin-oidc").register(shared);
require("./test-login-admin-native").register(shared);
require("./test-login-biber-oidc").register(shared);
require("./test-login-biber-ldap").register(shared);
require("./test-guest-persona").register(shared);
require("./test-biber-persona").register(shared);
require("./test-administrator-persona").register(shared);
require("./test-seaweedfs");
