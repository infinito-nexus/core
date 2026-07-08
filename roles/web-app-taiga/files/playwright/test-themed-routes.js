const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { isServiceEnabled } = require("./service-gating");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("taiga themed routes stay aligned across stable routes", async ({ page }) => {
    const session = await shared.loginToTaiga(page);

    const cssEnabled = isServiceEnabled("css");

    const routeChecks = [
      {
        url: session.discoverUrl,
        ready: page.getByRole("heading", { name: /discover projects/i }),
        surface: page.locator(".discover-header form"),
        field: page.locator(".discover-header input[type='text']"),
      },
      {
        url: session.projectsUrl,
        ready: page.getByRole("heading", { name: /my projects/i }),
        surface: page.locator(".project-list-wrapper .project-list-title, .project-list-title, .title-bar"),
      },
      {
        url: session.userSettingsUrl,
        ready: page.getByRole("heading", { name: /user settings/i }),
        surface: page.locator(".menu-secondary"),
      },
    ];

    for (const routeCheck of routeChecks) {
      await gotoOnion(page, routeCheck.url);
      await expect(routeCheck.ready).toBeVisible({ timeout: resolveTimeout(60_000) });

      if (!cssEnabled) {
        continue;
      }

      await shared.expectGradientBackground(
        page.locator("div.master"),
        `Expected the Taiga master background to stay themed on ${routeCheck.url}`,
      );

      if (routeCheck.surface) {
        await shared.expectGradientBackground(
          routeCheck.surface,
          `Expected the primary Taiga surface to stay themed on ${routeCheck.url}`,
        );
      }

      if (routeCheck.field) {
        await shared.expectGradientBackground(
          routeCheck.field,
          `Expected the Taiga input surface to stay themed on ${routeCheck.url}`,
        );
      }

      if (routeCheck.action) {
        await shared.expectGradientBackground(
          routeCheck.action,
          `Expected the main Taiga action button to stay themed on ${routeCheck.url}`,
        );
      }
    }

    await shared.logoutFromTaiga(page, session);
  });
};
