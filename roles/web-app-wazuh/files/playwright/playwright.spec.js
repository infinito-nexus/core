const { test } = require("@playwright/test");

const testBaseline = require("./test-baseline");
const testRbacRoles = require("./test-rbac-roles");
require("./test-csp");

test.describe.serial("wazuh: biber Keycloak group membership (single-owner)", () => {
  testBaseline.registerBiberBaseline();
  testRbacRoles.register();
});
