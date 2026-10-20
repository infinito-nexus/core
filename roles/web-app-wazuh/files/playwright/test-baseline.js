const { test, expect } = require("@playwright/test");
const { runGuestFlow, runBiberFlow, runAdminFlow, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

function registerBiberBaseline() {
  test("biber: dashboard → keycloak → view alerts → logout", async ({ page, browser }) => {
    skipUnlessServiceEnabled("sso");
    await shared.withBiberInGroup(browser, `${shared.env.rbacGroupPathPrefix}readonly-auditor`, () =>
      runBiberFlow(page, {
        biberInteraction: async (p) => {
          await expect(p.locator("body")).toContainText(/home|manage|dev tools/i, {
            timeout: resolveTimeout(30_000),
          });
        },
      }),
    );
  });
}

test("administrator: app → keycloak → admin action → logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (p) => {
      await gotoOnion(p, `${shared.env.appBaseUrl}/app/security-dashboards-plugin#/roles`);
      await expect(p.locator("body")).toContainText(/security|roles|users|management/i, {
        timeout: resolveTimeout(30_000),
      });
    },
  });
});

module.exports = { registerBiberBaseline };
