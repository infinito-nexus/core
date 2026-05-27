// Friendica Playwright spec — orchestration only. Shared env vars,
// login/logout flow helpers, variant selection, and the biber-account
// provisioning helper live in `_shared.js`; each scenario is registered
// from its own `test-*.js` companion module so each test stays atomar
// and individually inspectable.

const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({
  ignoreHTTPSErrors: true,
});

require("./test-guest-persona").register(shared);
require("./test-native-login-administrator").register(shared);
require("./test-side-by-side-sessions").register(shared);
require("./test-anonymous-profile-view").register(shared);
require("./test-admin-follow-biber").register(shared);
