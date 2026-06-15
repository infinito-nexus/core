const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(shared.beforeEach);

require("./test-csp").register(shared);
require("./test-admin-oidc-login").register(shared);
require("./test-biber-oidc-login").register(shared);
require("./test-admin-native-login").register(shared);
require("./test-admin-ldap-login").register(shared);
require("./test-biber-ldap-login").register(shared);
require("./test-guest-persona").register(shared);
require("./test-seaweedfs");
