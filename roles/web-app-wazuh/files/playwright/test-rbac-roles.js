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

async function seenBy(page) {
  const body = await page
    .locator("body")
    .innerText({ timeout: resolveTimeout(5_000) })
    .catch((err) => `<body text unavailable: ${err.message}>`);
  return `page: ${page.url()}, body: ${body.slice(0, 1500)}`;
}

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

          const nav = await gotoOnion(page, `${shared.env.appBaseUrl}/app/security-dashboards-plugin#/roles`, {
            waitUntil: "domcontentloaded",
          });
          expect(
            nav ? nav.status() : 0,
            `${tier.role} navigation to the Security management UI failed (${await seenBy(page)})`,
          ).toBeLessThan(400);
          const roleTable = page.locator("[data-test-subj='role-list']");

          if (tier.expectSecurityUi) {
            await roleTable
              .first()
              .waitFor({ state: "visible", timeout: resolveTimeout(30_000) })
              .catch(async (err) => {
                throw new Error(
                  `${tier.role} MUST reach the Security management UI (${await seenBy(page)}): ${err.message}`,
                );
              });
          } else {
            await page.waitForTimeout(resolveTimeout(10_000));
            const seen = await seenBy(page);
            // Exception: the explicit denial text is not verified yet; these two checks stand in for it until CI shows what a denied user sees.
            expect(
              page.url().startsWith(shared.env.appBaseUrl),
              `${tier.role} MUST be denied inside the Wazuh app, not redirected away (${seen})`,
            ).toBe(true);
            expect(
              (await page.locator("body").innerText({ timeout: resolveTimeout(5_000) })).trim(),
              `${tier.role} MUST see a denial or empty-permission page, not a blank page (${seen})`,
            ).not.toBe("");
            await expect(
              roleTable,
              `${tier.role} MUST NOT reach the Security management UI (role table rendered, ${seen})`,
            ).toHaveCount(0);
            await expect(
              page.locator("[data-test-subj='create-role']"),
              `${tier.role} MUST NOT reach the Security management UI (create-role button rendered, ${seen})`,
            ).toHaveCount(0);
          }
        } finally {
          await biberCtx.close().catch(() => {});
        }
      });
    });
  }
};
