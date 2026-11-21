const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(shared.beforeEach);

require("./test-atmo-landing").register(shared);
require("./test-atmo-oauth-client").register(shared);
require("./test-atmo-cron-guard").register(shared);

require("./test-guest-persona").register(shared);
require("./test-biber-persona").register(shared);
require("./test-administrator-persona").register(shared);
