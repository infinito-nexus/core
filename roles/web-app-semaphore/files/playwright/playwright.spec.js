const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({
  ignoreHTTPSErrors: true,
});

test.beforeEach(shared.beforeEach);

require("./test-guest").register(shared);
require("./test-login-methods").register(shared);
require("./test-login-native-administrator").register(shared);
require("./test-login-oidc-administrator").register(shared);
require("./test-login-oidc-biber").register(shared);
require("./test-login-ldap-biber").register(shared);
require("./test-login-ldap-administrator").register(shared);
require("./test-app-control-outsider").register(shared);
require("./test-app-control-operator").register(shared);
require("./test-design").register(shared);
require("./test-foreign-deploy").register(shared);
require("./test-workspace-runners").register(shared);
require("./test-workspace-export").register(shared);
require("./test-workspace-usage").register(shared);
require("./test-workspace-monitoring").register(shared);
require("./test-provision").register(shared);
require("./test-task-token").register(shared);
require("./test-workspace-logins").register(shared);
