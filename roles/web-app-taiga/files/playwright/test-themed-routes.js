const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { isServiceEnabled } = require("./service-gating");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("taiga themed routes stay aligned across stable routes", async ({ page }) => {
    const session = await shared.loginToTaigaForVariant(page);

    const cssEnabled = isServiceEnabled("design");

    const routeChecks = [
      {
        url: session.discoverUrl,
        ready: page.getByRole("heading", { name: /discover projects/i }),
        surfaces: [[".discover-header", "--design-surface-3"]],
      },
      {
        url: session.projectsUrl,
        ready: page.getByRole("heading", { name: /my projects/i }),
        surfaces: [],
      },
      {
        url: session.userSettingsUrl,
        ready: page.getByRole("heading", { name: /user settings/i }),
        surfaces: [[".menu-secondary", "--design-surface-2"]],
      },
    ];

    for (const routeCheck of routeChecks) {
      await gotoOnion(page, routeCheck.url);
      await expect(routeCheck.ready).toBeVisible({ timeout: resolveTimeout(60_000) });

      if (!cssEnabled) {
        continue;
      }

      await shared.expectTokenSurface(page, "nav.navbar", "--design-frame", `Taiga navbar on ${routeCheck.url}`);
      for (const [selector, token] of routeCheck.surfaces) {
        await shared.expectTokenSurface(page, selector, token, `Taiga surface ${selector} on ${routeCheck.url}`);
      }
    }
  });
};
