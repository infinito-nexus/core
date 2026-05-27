const { test } = require("@playwright/test");

// Placeholder until the full per-site Multisite scenarios (three canonical
// domains, network-administrator grant/revoke) land. The skip surfaces
// explicitly in the reporter so contributors see which scenarios are out
// of scope for a Single-Site deploy.
exports.register = function (shared) {
  test("wordpress multisite per-site RBAC is not exercised in single-site deploys", async () => {
    test.skip(
      !shared.env.multisiteEnabled,
      "WORDPRESS_MULTISITE_ENABLED=false; Multisite scenarios run only when the role flag is true"
    );
  });
};
