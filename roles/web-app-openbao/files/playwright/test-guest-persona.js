const { test } = require("@playwright/test");
const { runGuestFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("guest: landing -> auth chain, never an authenticated surface", async ({ page }) => {
  await runGuestFlow(page);
});
