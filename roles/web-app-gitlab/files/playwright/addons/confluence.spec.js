const { test } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { expectInstanceIntegrationIsAdminOnly } = require("../test-integrations");

test.use({ ignoreHTTPSErrors: true });

test("addon confluence: GitLab serves the Confluence integration surface for the deployed partner", async ({ page }) => {
  skipUnlessAddonEnabled("confluence");
  skipUnlessServiceEnabled("confluence");

  await expectInstanceIntegrationIsAdminOnly(page, "confluence", "Confluence");
});
