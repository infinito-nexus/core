const { test, expect } = require("@playwright/test");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("fediwall root resolves to the configured default slug", async ({ page }) => {
    await gotoOnion(page, `${shared.env.appBaseUrl}/`);
    if (shared.env.wallSlugs.length <= 1) {
      // Single-wall deploy: root MUST redirect to the only wall's path.
      await expect(page).toHaveURL(new RegExp(`/${shared.env.defaultSlug}/?$`));
    } else {
      // Multi-wall deploy: root MUST present an entry for every slug.
      for (const slug of shared.env.wallSlugs) {
        await expect(page.locator(`a[href="./${slug}/"]`)).toBeVisible();
      }
    }
  });
};
