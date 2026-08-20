const { test, expect } = require("@playwright/test");

const { appBaseUrl, canonicalDomain } = require("./env");

// Aggregator: the runner collects only *.spec.js; the scenarios live in the
// test-*.js modules required below (TLS/DAV baseline, WebAdmin SSO, the
// Roundcube mail flow, and the shared persona flows).
test.use({ ignoreHTTPSErrors: true });

test.beforeEach(() => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
});

require("./test-tls");
require("./test-sso");
require("./test-mailflow");
require("./test-personas");
