const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("fediwall default slug mounts its Vue SPA into the document body", async ({ page }) => {
    await page.goto(`${shared.env.appBaseUrl}/${shared.env.defaultSlug}/`);
    await expect(page.locator("#app")).toBeAttached();
  });
};
