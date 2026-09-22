const { test } = require("@playwright/test");
const { runAdminFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("administrator: app -> admin surface -> universal logout", async ({ page }) => {
  await runAdminFlow(page);
});
