const { test } = require("@playwright/test");

const testBaseline = require("./test-baseline");
const testRbacRoles = require("./test-rbac-roles");
const testDesign = require("./test-design");
require("./test-csp");

testDesign.register();

test.describe.serial("wazuh: biber Keycloak group membership (single-owner)", () => {
  testBaseline.registerBiberBaseline();
  testRbacRoles.register();
});
