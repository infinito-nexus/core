const { test, expect } = require("./onion-test");

const { gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");
const {
  accountChoice,
  expectDashboardSignedOut,
  logOutThisDeviceFromAccountMenu,
  logoutEnv,
  openAccountMenu,
  openContext,
  signInToDashboard,
} = require("./logout-flow");

const CONFIRM = "#kc-logout";
const EVERYWHERE = "#kc-logout-everywhere";

/**
 * Args:
 *   page: a page of the context that looks at the confirmation page.
 */
async function expectBothChoicesOnConfirmation(page) {
  await gotoOnion(page, logoutEnv.logoutUrl);
  await expect(page.locator(CONFIRM), "Log out on this device is the confirmation submit").toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  const link = page.locator(EVERYWHERE);
  await expect(link, "Log out everywhere sits next to it").toBeVisible({ timeout: resolveTimeout(30_000) });
  const target = new URL(await link.getAttribute("href"));
  expect(target.search, "the everywhere link carries no query parameter").toBe("");
  expect(target.hash, "the everywhere link carries only the marker").toBe(logoutEnv.everywhereMarker);
  expect(
    logoutEnv.dashboardUrls.map((url) => new URL(url).origin),
    "the everywhere link leads to the dashboard",
  ).toContain(target.origin);
}

exports.register = function () {
  test.describe("logout-choices", () => {
    test.beforeEach(() => {
      test.skip(
        logoutEnv.dashboardUrls.length === 0,
        "DASHBOARD_URLS_JSON is empty: without the dashboard with OIDC the confirmation page offers no Log out everywhere",
      );
    });

    test("logout-choices: the confirmation page offers both choices with JavaScript", async ({ browser }) => {
      const context = await openContext(browser, true);
      try {
        await expectBothChoicesOnConfirmation(await context.newPage());
      } finally {
        await context.close();
      }
    });

    test("logout-choices: the confirmation page offers both choices without JavaScript", async ({ browser }) => {
      test.skip(
        !logoutEnv.keycloakThemeEnabled,
        "KEYCLOAK_THEME_ENABLED is false: the stock theme renders the everywhere link through the logout panel, which needs JavaScript",
      );
      const context = await openContext(browser, false);
      try {
        await expectBothChoicesOnConfirmation(await context.newPage());
      } finally {
        await context.close();
      }
    });

    test("logout-choices: the dashboard Account menu offers both choices", async ({ browser }) => {
      test.setTimeout(resolveTimeout(180_000)); // a dashboard OIDC round trip plus the logout sweep that ends the scenario
      const context = await openContext(browser);
      try {
        const page = await context.newPage();
        const dashboard = logoutEnv.dashboardUrls[0];
        await signInToDashboard(page, dashboard);
        await openAccountMenu(page);
        await expect(accountChoice(page, "device")).toBeVisible({ timeout: resolveTimeout(10_000) });
        const everywhere = accountChoice(page, "everywhere");
        await expect(everywhere).toBeVisible({ timeout: resolveTimeout(10_000) });
        await openAccountMenu(page);
        await logOutThisDeviceFromAccountMenu(page);
        await expectDashboardSignedOut(page, dashboard);
      } finally {
        await context.close();
      }
    });
  });
};
