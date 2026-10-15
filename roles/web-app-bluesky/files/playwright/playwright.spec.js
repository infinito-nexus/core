const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(shared.beforeEach);

require("./test-baseline").register(shared);
require("./test-oidc-broker-handoff").register(shared);
require("./test-appview-oidc-api").register(shared);
require("./test-appview-oidc-render").register(shared);
require("./test-appview-native").register(shared);
require("./test-native-admin").register(shared);
require("./test-guest-persona").register(shared);
require("./test-biber-persona").register(shared);
require("./test-administrator-persona").register(shared);
