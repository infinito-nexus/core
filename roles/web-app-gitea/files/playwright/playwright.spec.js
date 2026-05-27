// Gitea Playwright spec — orchestration only. Shared env + persona
// helpers live in `_shared.js`; each scenario is registered from its
// own `test-*.js` companion module so each test stays atomar and
// individually inspectable.

const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({
  ignoreHTTPSErrors: true,
});

test.beforeEach(shared.beforeEach);

require("./test-healthz-ready").register(shared);
require("./test-guest-persona").register(shared);
require("./test-biber-persona").register(shared);
require("./test-administrator-persona").register(shared);
