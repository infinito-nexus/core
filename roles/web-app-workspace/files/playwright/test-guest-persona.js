const { test } = require("@playwright/test");
const { runGuestFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("guest: anonymous visit is pushed into SSO and never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});
