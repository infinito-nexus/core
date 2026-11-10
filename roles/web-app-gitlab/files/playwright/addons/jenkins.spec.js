const { test } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { expectInstanceIntegrationIsAdminOnly } = require("../test-integrations");

test.use({ ignoreHTTPSErrors: true });

test("addon jenkins: GitLab serves the Jenkins integration surface for the deployed partner", async ({ page }) => {
  skipUnlessAddonEnabled("jenkins");
  skipUnlessServiceEnabled("jenkins");

  await expectInstanceIntegrationIsAdminOnly(page, "jenkins", "Jenkins");
});
