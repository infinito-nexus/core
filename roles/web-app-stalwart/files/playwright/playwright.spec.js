const { test, expect } = require("@playwright/test");

const { appBaseUrl, canonicalDomain } = require("./env");

// Aggregator: the runner collects only *.spec.js; the scenarios live in the
// test-*.js modules required below (TLS/DAV baseline, WebAdmin SSO and native
// login, the Roundcube mail flow both ways, the .onion outbound route, and the
// shared persona flows). A module missing from this list is never collected.
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
