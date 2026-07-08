const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("taiga public discover keeps the themed surface", async ({ page }) => {
    shared.skipUnlessServiceEnabled("css");

    const taigaUrls = shared.getTaigaUrls();

    await page.goto(taigaUrls.discoverUrl);
    await expect(page.getByRole("heading", { name: /discover projects/i })).toBeVisible({ timeout: resolveTimeout(60_000) });
    await shared.expectGradientBackground(
      page.locator("div.master"),
      "Expected the Taiga discover page to use the themed master background",
    );
    await shared.expectGradientBackground(
      page.locator(".discover-header form"),
      "Expected the Taiga discover search form to use the themed surface",
    );
    await shared.expectGradientBackground(
      page.locator(".discover-header input[type='text']"),
      "Expected the Taiga discover search input to use the themed input surface",
    );
  });
};
