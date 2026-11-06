const { test } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { expectInstanceIntegrationIsAdminOnly } = require("../test-integrations");

test.use({ ignoreHTTPSErrors: true });

test("addon mattermost: GitLab serves the Mattermost notifications integration surface for the deployed partner", async ({ page }) => {
  skipUnlessAddonEnabled("mattermost");
  skipUnlessServiceEnabled("mattermost");

  await expectInstanceIntegrationIsAdminOnly(page, "mattermost", "Mattermost notifications");
});
