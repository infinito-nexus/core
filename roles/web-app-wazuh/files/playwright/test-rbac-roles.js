const { test, expect } = require("@playwright/test");
const { installCspViolationObserver } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const shared = require("./_shared");

// Three roles across the privilege spectrum. playwright.spec.js registers
// this loop inside a test.describe.serial block shared with
// test-baseline.js's biber test, so these tiers and that test never run
// concurrently: all four tests mutate the same Keycloak "biber" user's
// group membership (this loop across all three tiers, test-baseline.js
// specifically the readonly-auditor group), and concurrent add/remove
// cycles under PLAYWRIGHT_FULLY_PARALLEL would otherwise race.
//
// expectSecurityUi is asserted against the LIVE rendered page, never
// inferred from templates/roles.yml permissions: the analyst check
// specifically MUST be a real UI-level assertion (element not present /
// route not reachable), per the role's contract.
//
// A positive "has write actions" UI check (e.g. an enabled restart/upgrade
// button) was deliberately NOT added here: Wazuh's own agent-management
// views only render those controls for enrolled agents, and agent
// enrollment is explicitly out of scope for this role, so the check would
// be untestable in this environment regardless of role. A read-only-mode
// UI banner was considered as an agent-independent alternative, but
// OpenSearch Dashboards' own ReadonlyService (server/readonly/readonly_service.js)
// only activates when multitenancy is enabled - confirmed by reading that
// file directly - and this role runs with
// opensearch_security.multitenancy.enabled: false, so no such banner ever
// appears here. See README.md for the same note.
const RBAC_TIERS = [
  { role: "administrator", expectSecurityUi: true },
  { role: "security-analyst", expectSecurityUi: false },
  { role: "readonly-auditor", expectSecurityUi: false },
];

exports.register = function () {
  for (const tier of RBAC_TIERS) {
    test(`rbac: membership in ${tier.role} group grants the expected Wazuh UI surface`, async ({
      browser,
    }) => {
      skipUnlessServiceEnabled("sso");
      const groupPath = `${shared.env.rbacGroupPathPrefix}${tier.role}`;
      let biberAdded = false;

      const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        biberAdded = await shared.keycloakAdminAddUserToGroup(
          adminCtx.request,
          shared.env.keycloakBaseUrl,
          shared.env.realmName,
          groupPath,
          shared.env.biberUsername,
        );

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

          // Real UI-level assertion (not an inference from roles.yml):
          // navigate directly to OpenSearch Dashboards' own Security app.
          // Non-admin OpenSearch roles never receive the cluster-admin
          // security actions, so OpenSearch Dashboards itself refuses to
          // render (or navigates away from) this app for them — the same
          // mechanism that decides whether the "Security" nav link even
          // appears.
          await page
            .goto(`${shared.env.appBaseUrl}/app/security-dashboards-plugin#/roles`, {
              waitUntil: "domcontentloaded",
            })
            .catch(() => {});
          // `.isVisible({timeout})` does NOT poll/retry for up to `timeout` -
          // it's a near-instant check (confirmed against a live deploy: a
          // dynamically-promoted administrator's session failed this check
          // in 1.5s despite a configured 30s timeout, while the actual page
          // was still rendering "Loading ..." well past that point in a
          // manual reproduction). `.waitFor({state, timeout})` is the real
          // polling primitive; wrapped here to still resolve to a boolean.
          const securityUiVisible = await page
            .getByText(/internal users|role mappings|create role/i)
            .first()
            .waitFor({ state: "visible", timeout: 30_000 })
            .then(() => true)
            .catch(() => false);
          const deniedMarker = await page
            .getByText(/no permissions|not authorized|forbidden|missing.*permission/i)
            .first()
            .waitFor({ state: "visible", timeout: 10_000 })
            .then(() => true)
            .catch(() => false);

          if (tier.expectSecurityUi) {
            expect(
              securityUiVisible,
              `${tier.role} MUST reach the Security management UI (page: ${page.url()})`,
            ).toBe(true);
          } else {
            expect(
              securityUiVisible === false || deniedMarker === true,
              `${tier.role} MUST NOT reach the Security management UI (saw content=${securityUiVisible}, denied-marker=${deniedMarker}, page: ${page.url()})`,
            ).toBe(true);
          }
        } finally {
          await biberCtx.close().catch(() => {});
        }
      } finally {
        if (biberAdded) {
          await shared
            .keycloakRemoveUserFromGroupViaRest(
              adminCtx.request,
              shared.env.keycloakBaseUrl,
              shared.env.realmName,
              shared.env.superAdminUsername,
              shared.env.superAdminPassword,
              groupPath,
              shared.env.biberUsername,
            )
            .catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
        }
        await adminCtx.close().catch(() => {});
      }
    });
  }
};
