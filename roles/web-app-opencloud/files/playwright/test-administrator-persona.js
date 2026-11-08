const { test } = require("./onion-test");

const { runAdminFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page);
});
