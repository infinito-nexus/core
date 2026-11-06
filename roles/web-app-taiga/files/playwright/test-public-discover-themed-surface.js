const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("taiga public discover keeps the themed surface", async ({ page }) => {
    shared.skipUnlessServiceEnabled("design");

    const taigaUrls = shared.getTaigaUrls();

    await gotoOnion(page, taigaUrls.discoverUrl);
    await expect(page.getByRole("heading", { name: /discover projects/i })).toBeVisible({ timeout: resolveTimeout(60_000) });
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await shared.expectTokenSurface(page, "nav.navbar", "--design-frame", `taiga discover navbar ${mode}`);
      await shared.expectTokenSurface(page, ".discover-header", "--design-surface-3", `taiga discover header ${mode}`);
      await shared.expectTokenSurface(
        page,
        ".discover-header input[type='text']",
        "--design-surface-1",
        `taiga discover search field ${mode}`,
      );
    }
    await page.emulateMedia({ colorScheme: null });
  });
};
