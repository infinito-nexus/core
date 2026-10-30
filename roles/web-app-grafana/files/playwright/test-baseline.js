const { test, expect } = require("@playwright/test");
const { runGuestFlow, runBiberFlow, runAdminFlow, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: grafana → keycloak → open the central log dashboard as auditor → logout", async ({ page, browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));
  await shared.withBiberInGroup(browser, shared.env.auditorGroupPath, () =>
    runBiberFlow(page, {
      biberInteraction: async (p) => {
        await gotoOnion(p, `${shared.env.appBaseUrl}/d/infinito-logs`, { waitUntil: "domcontentloaded" });
        await expect(p.locator("body")).toContainText(/Application Logs/, { timeout: resolveTimeout(60_000) });
      },
    }),
  );
});

test("administrator: grafana → keycloak → open the datasource administration → logout", async ({ page }) => {
  test.setTimeout(resolveTimeout(180_000));
  await runAdminFlow(page, {
    adminInteraction: async (p) => {
      await gotoOnion(p, `${shared.env.appBaseUrl}/connections/datasources`, { waitUntil: "domcontentloaded" });
      await expect(p.locator("body")).toContainText(/data sources|add new data source|loki|prometheus/i, {
        timeout: resolveTimeout(60_000),
      });
    },
  });
});
