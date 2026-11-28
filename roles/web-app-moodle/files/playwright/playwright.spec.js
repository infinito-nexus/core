const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(shared.beforeEach);

require("./test-baseline").register(shared);
require("./test-ldap-variant").register(shared);
require("./test-login-methods").register(shared);
require("./test-2fa-enrollment").register(shared);
require("./test-profile-readonly").register(shared);
require("./test-profile-sync").register(shared);
require("./test-keycloak-scope").register(shared);
require("./test-lam-writethrough").register(shared);
require("./test-administrator-persona").register(shared);
require("./test-rbac-roles").register(shared);
require("./test-guest-persona").register(shared);
require("./test-mcp-guest").register(shared);
require("./test-litellm-gateway").register(shared);
require("./test-seaweedfs").register(shared);
require("./test-design").register(shared);
