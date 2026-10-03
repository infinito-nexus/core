const { test, expect } = require("@playwright/test");
const { installCspViolationObserver } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const shared = require("./_shared");

const RBAC_TIERS = [
  { role: "administrator", expectSecurityUi: true },
  { role: "security-analyst", expectSecurityUi: false },
  { role: "readonly-auditor", expectSecurityUi: false },
];

function becomesVisible(locator, timeout) {
  return locator
    .first()
    .waitFor({ state: "visible", timeout: resolveTimeout(timeout) })
    .then(() => true)
    .catch(() => false);
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

          await page
            .goto(`${shared.env.appBaseUrl}/app/security-dashboards-plugin#/roles`, {
              waitUntil: "domcontentloaded",
            })
            .catch(() => {});
          const securityUiVisible = await becomesVisible(
            page.getByText(/internal users|role mappings|create role/i),
            30_000,
          );

          if (tier.expectSecurityUi) {
            expect(
              securityUiVisible,
              `${tier.role} MUST reach the Security management UI (page: ${page.url()})`,
            ).toBe(true);
          } else {
            const deniedMarker = await becomesVisible(
              page.getByText(/no permissions|not authorized|forbidden|missing.*permission/i),
              10_000,
            );
            expect(
              securityUiVisible === false || deniedMarker === true,
              `${tier.role} MUST NOT reach the Security management UI (saw content=${securityUiVisible}, denied-marker=${deniedMarker}, page: ${page.url()})`,
            ).toBe(true);
          }
        } finally {
          await biberCtx.close().catch(() => {});
        }
      });
    });
  }
};
