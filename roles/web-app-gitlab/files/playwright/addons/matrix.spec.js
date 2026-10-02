const { test } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { expectInstanceIntegrationIsAdminOnly } = require("../test-integrations");

test.use({ ignoreHTTPSErrors: true });

test("addon matrix: GitLab serves the Matrix notifications integration surface for the deployed partner", async ({ page }) => {
  skipUnlessAddonEnabled("matrix");
  skipUnlessServiceEnabled("matrix");

  await expectInstanceIntegrationIsAdminOnly(page, "matrix", "Matrix");
});
