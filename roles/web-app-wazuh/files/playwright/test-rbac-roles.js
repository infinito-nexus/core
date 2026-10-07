const { test, expect } = require("@playwright/test");
const { installCspViolationObserver, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const shared = require("./_shared");

const RBAC_TIERS = [
  { role: "administrator", expectSecurityUi: true },
  { role: "security-analyst", expectSecurityUi: false },
  { role: "readonly-auditor", expectSecurityUi: false },
];

const ROLES_API_PATH = "/api/v1/configuration/roles";

exports.register = function () {
  for (const tier of RBAC_TIERS) {
    test(`rbac: membership in ${tier.role} group grants the expected Wazuh UI surface`, async ({
      browser,
    }) => {
      skipUnlessServiceEnabled("sso");
      await shared.withBiberInGroup(browser, `${shared.env.rbacGroupPathPrefix}${tier.role}`, async () => {
        const biberCtx = await browser.newContext({ ignoreHTTPSErrors: true });
        try {
          const page = await biberCtx.newPage();
          await installCspViolationObserver(page);
          await shared.wazuhLoginViaOidc(
            page,
            shared.env.appBaseUrl,
            shared.env.biberUsername,
            shared.env.biberPassword,
          );

          const rolesApi = page.waitForResponse(
            (r) => r.request().method() === "GET" && new URL(r.url()).pathname.endsWith(ROLES_API_PATH),
            { timeout: resolveTimeout(60_000) },
          );
          const nav = await gotoOnion(page, `${shared.env.appBaseUrl}/app/security-dashboards-plugin#/roles`, {
            waitUntil: "domcontentloaded",
          });
          expect(
            nav ? nav.status() : 0,
            `${tier.role} navigation to the Security management UI failed (page: ${page.url()})`,
          ).toBeLessThan(400);
          const rolesStatus = (await rolesApi).status();
          const roleTable = page.locator("[data-test-subj='role-list']");

          if (tier.expectSecurityUi) {
            expect(
              rolesStatus,
              `${tier.role} MUST reach the Security management UI (roles API ${rolesStatus}, page: ${page.url()})`,
            ).toBe(200);
            await expect(
              roleTable,
              `${tier.role} MUST reach the Security management UI (page: ${page.url()})`,
            ).toBeVisible({ timeout: resolveTimeout(30_000) });
          } else {
            expect(
              rolesStatus,
              `${tier.role} MUST NOT reach the Security management UI (roles API ${rolesStatus}, page: ${page.url()})`,
            ).toBe(403);
            await expect(
              roleTable,
              `${tier.role} MUST NOT reach the Security management UI (role table rendered, page: ${page.url()})`,
            ).toHaveCount(0);
            await expect(
              page.locator("[data-test-subj='create-role']"),
              `${tier.role} MUST NOT reach the Security management UI (create-role button rendered, page: ${page.url()})`,
            ).toHaveCount(0);
          }
        } finally {
          await biberCtx.close().catch(() => {});
        }
      });
    });
  }
};
