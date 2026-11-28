const { test } = require("@playwright/test");
const { runGuestFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});
