const { test } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { expectInstanceIntegrationIsAdminOnly } = require("../test-integrations");

test.use({ ignoreHTTPSErrors: true });

test("addon jira: GitLab serves the Jira integration surface for the deployed partner", async ({ page }) => {
  skipUnlessAddonEnabled("jira");
  skipUnlessServiceEnabled("jira");

  await expectInstanceIntegrationIsAdminOnly(page, "jira", "Jira");
});
