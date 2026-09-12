const { test, expect } = require("@playwright/test");

const { appBaseUrl, canonicalDomain } = require("./env");

// The runner collects only *.spec.js, so a test-*.js module missing from the
// list below is never run.
test.use({ ignoreHTTPSErrors: true });

test.beforeEach(() => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
});

require("./test-tls");
require("./test-sso");
require("./test-login-native");
require("./test-mailflow");
require("./test-onion-mailflow");
require("./test-personas");
