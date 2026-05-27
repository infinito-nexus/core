const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(shared.beforeEach);

require("./test-csp").register(shared);
require("./test-admin-oidc-login").register(shared);
require("./test-rbac-roles").register(shared);
require("./test-multisite-skip").register(shared);
require("./test-discourse-roundtrip").register(shared);
require("./test-guest-persona").register(shared);
require("./test-biber-persona").register(shared);
require("./test-administrator-persona").register(shared);
