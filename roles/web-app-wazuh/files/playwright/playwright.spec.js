const { test } = require("@playwright/test");

// require() runs test-baseline.js's module body immediately, which
// registers the guest/administrator tests as an eager side effect and
// exports registerBiberBaseline() for the serial block below (see that
// file's comment on why the biber test isn't also registered eagerly).
const testBaseline = require("./test-baseline");
const testRbacRoles = require("./test-rbac-roles");
// Registers its "wazuh dashboard: ..." test as an eager side effect of
// require(), same as test-baseline.js's "administrator" test above: it
// touches no shared Keycloak group state, so it needs no serial ordering.
require("./test-csp");

// Single-owner serial block for every test that mutates the "biber" user's
// Keycloak group membership, so PLAYWRIGHT_FULLY_PARALLEL + multiple
// workers can never interleave their add/remove cycles against the same
// groups (see test-baseline.js and test-rbac-roles.js for the full
// reasoning). guest/administrator stay outside this block since they
// touch no shared Keycloak group state.
test.describe.serial("wazuh: biber Keycloak group membership (single-owner)", () => {
  testBaseline.registerBiberBaseline();
  testRbacRoles.register();
});
