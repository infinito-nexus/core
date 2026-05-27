const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(shared.beforeEach);

require("./test-baseline").register(shared);
require("./test-ldap-variant").register(shared);
require("./test-profile-readonly").register(shared);
require("./test-keycloak-scope").register(shared);
require("./test-lam-writethrough").register(shared);
require("./test-administrator-persona").register(shared);
require("./test-guest-persona").register(shared);
