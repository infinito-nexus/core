const { test, expect } = require("@playwright/test");
const { runGuestFlow, runBiberFlow, runAdminFlow } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

// biber starts with no Wazuh group membership (the fixture's generic
// "regular end-user" account, deliberately blank-slate — see
// docs/contributing/artefact/files/role/playwright.specs.js.md). To give
// biber a real interaction to drive, this test grants readonly-auditor
// membership for the duration of the test only, via the Keycloak Admin
// REST API (same technique as roles/web-app-wordpress/files/playwright/
// test-rbac-roles.js), and always removes it again in `finally`.
//
// Registered via an exported function (not run at module scope) so
// playwright.spec.js can group it into the same `test.describe.serial`
// block as test-rbac-roles.js's RBAC_TIERS loop: both mutate the SAME
// Keycloak "readonly-auditor" group for the SAME "biber" user. Running
// them concurrently (PLAYWRIGHT_FULLY_PARALLEL=true with
// PLAYWRIGHT_WORKERS>1 — both worker/scheduling knobs this suite exposes)
// previously raced their independent add/remove cycles: each call sees
// "not yet a member", each adds it (harmless, idempotent) and believes it
// owns the membership, then whichever test's `finally` cleanup runs first
// revokes it out from under the other mid-flow. Serial execution removes
// the race outright instead of just narrowing its window.
function registerBiberBaseline() {
  test("biber: dashboard → keycloak → view alerts → logout", async ({ page, browser }) => {
    // The group-membership setup below talks to the Keycloak Admin REST API
    // directly, ahead of (and independent from) runBiberFlow's own internal
    // PERSONA_BIBER_BLOCKED / sso gating. With sso off, V1 deploys no
    // Keycloak at all, so that setup call would fail with a misleading
    // "Keycloak user biber not found" instead of a clean skip. Same
    // service-gate convention as test-rbac-roles.js, which talks to the same
    // Keycloak Admin API for the same reason.
    skipUnlessServiceEnabled("sso");
    const groupPath = `${shared.env.rbacGroupPathPrefix}readonly-auditor`;
    let biberAdded = false;
    const setupCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      biberAdded = await shared.keycloakAdminAddUserToGroup(
        setupCtx.request,
        shared.env.keycloakBaseUrl,
        shared.env.realmName,
        groupPath,
        shared.env.biberUsername,
      );

      await runBiberFlow(page, {
        biberInteraction: async (p) => {
          // Wazuh's own wz-home app throws an uncaught client-side exception
          // during its bootstrap for any OpenSearch role other than
          // all_access - confirmed against a live deploy via a full network
          // waterfall comparison against a working administrator session,
          // and confirmed to be a genuine Wazuh-side bug (not a permission
          // gap on this role's side, and not specific to wz-home reached as
          // the landing page - a fresh direct navigation to another
          // Wazuh-specific view hit the same failure). Because of that,
          // uiSettings.overrides.defaultRoute (opensearch_dashboards.yml.j2)
          // points at OpenSearch Dashboards' own framework-standard
          // "/app/home" instead of wz-home, which is confirmed to render
          // correctly for every role. This assertion checks that landing
          // page's own real content, proving the authenticated session is
          // genuinely live and stable, not just that a login redirect fired.
          await expect(p.locator("body")).toContainText(/home|manage|dev tools/i, {
            timeout: 30_000,
          });
        },
      });
    } finally {
      if (biberAdded) {
        await shared
          .keycloakRemoveUserFromGroupViaRest(
            setupCtx.request,
            shared.env.keycloakBaseUrl,
            shared.env.realmName,
            shared.env.superAdminUsername,
            shared.env.superAdminPassword,
            groupPath,
            shared.env.biberUsername,
          )
          .catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
      }
      await setupCtx.close().catch(() => {});
    }
  });
}

// The platform's standard "administrator" fixture user is already a member
// of every app's rbac_group_path administrator group (see
// roles/web-app-wordpress/files/playwright/test-administrator-persona.js,
// which needs no dynamic group setup either), so no setup/teardown is
// needed here.
test("administrator: app → keycloak → admin action → logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (p) => {
      // Direct navigation instead of clicking a nav link: Wazuh's own
      // navigation lives behind a collapsed hamburger menu rather than
      // always-visible top-level links, and a prior regex-based link click
      // here hit an unimplemented route ("Application Not Found" - confirmed
      // via screenshot once OIDC login itself was confirmed working). This
      // matches the same direct-URL approach test-rbac-roles.js already
      // uses successfully for the same security-dashboards-plugin view.
      await p.goto(`${shared.env.appBaseUrl.replace(/\/$/, "")}/app/security-dashboards-plugin#/roles`);
      await expect(p.locator("body")).toContainText(/security|roles|users|management/i, {
        timeout: 30_000,
      });
    },
  });
});

module.exports = { registerBiberBaseline };
