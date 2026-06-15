const { test } = require("@playwright/test");

const { runBiberFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});
