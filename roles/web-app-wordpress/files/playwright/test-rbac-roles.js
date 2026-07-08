const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { installCspViolationObserver } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

// Auto-provisioned LDAP/Keycloak groups drive WordPress roles via the
// OIDC `groups` claim, consumed by the mu-plugin
// infinito-oidc-rbac-mapper.php. Test three roles across the privilege
// spectrum serially so a regression in one mapping does not mask another.
const RBAC_ROLE_SEQUENCE = ["subscriber", "editor", "administrator"];

// Keycloak group path is hierarchical:
// /roles/web-app-wordpress/<role> (Single-Site) or
// /roles/web-app-wordpress/<tenant>/<role> (Multisite).
// RBAC_GROUP_PATH_PREFIX renders `/roles/web-app-wordpress/`; the spec
// appends the role segment. Multisite scenarios opt in via
// services.wordpress.multisite.enabled = true.

exports.register = function (shared) {
  for (const role of RBAC_ROLE_SEQUENCE) {
    test(`rbac: membership in ${role} group grants WordPress ${role} role`, async ({
      browser,
    }) => {
      skipUnlessServiceEnabled("sso");
      skipUnlessServiceEnabled("ldap");
      test.skip(
        shared.env.multisiteEnabled,
        "WORDPRESS_MULTISITE_ENABLED=true; Single-Site RBAC scenarios run only when Multisite is disabled"
      );
      const groupPath = `${shared.env.rbacGroupPathPrefix}${role}`;
      let biberAddedToGroup = false;

      // Each identity runs in its own isolated context so WP session
      // cookies, Keycloak SSO cookies, and OIDC post-logout redirect
      // state cannot leak between super-admin, biber, and wp-admin hops.
      const newCtx = async () => {
        const ctx = await browser.newContext({
          ignoreHTTPSErrors: true,
          viewport: { width: 1440, height: 1100 },
        });
        const p = await ctx.newPage();
        await installCspViolationObserver(p);
        return { ctx, page: p };
      };

      try {
        const adminKc = await newCtx();
        try {
          await adminKc.page.goto(`${shared.env.keycloakBaseUrl}/admin/master/console/`);
          await shared.fillKeycloakLoginForm(
            adminKc.page,
            shared.env.superAdminUsername,
            shared.env.superAdminPassword
          );
          await expect
            .poll(() => adminKc.page.url(), {
              timeout: resolveTimeout(60_000),
              message: "Expected to land in the Keycloak admin console",
            })
            .toContain("/admin/master/console/");
          biberAddedToGroup = await shared.keycloakAdminAddUserToGroup(
            adminKc.page,
            shared.env.keycloakBaseUrl,
            shared.env.realmName,
            groupPath,
            shared.env.biberUsername
          );
        } finally {
          await adminKc.ctx.close().catch(() => {});
        }

        const biberWp = await newCtx();
        try {
          await shared.wpAdminLoginViaOidc(
            biberWp.page,
            shared.env.wpBaseUrl,
            shared.env.biberUsername,
            shared.env.biberPassword
          );
        } finally {
          await biberWp.ctx.close().catch(() => {});
        }

        const wpAdmin = await newCtx();
        try {
          await shared.wpAdminLoginViaOidc(
            wpAdmin.page,
            shared.env.wpBaseUrl,
            shared.env.adminUsername,
            shared.env.adminPassword
          );
          await wpAdmin.page.goto(`${shared.env.wpBaseUrl}/wp-admin/users.php`, {
            waitUntil: "domcontentloaded",
          });
          const biberRow = wpAdmin.page
            .locator("tr")
            .filter({ hasText: new RegExp(shared.env.biberUsername, "i") })
            .first();
          await expect(
            biberRow,
            `Expected biber row to be visible on /wp-admin/users.php`
          ).toBeVisible({ timeout: resolveTimeout(30_000) });
          const rowText = (await biberRow.textContent()) || "";
          const expectedLabel = role.charAt(0).toUpperCase() + role.slice(1);
          expect(
            rowText.includes(expectedLabel),
            `biber's row on /wp-admin/users.php MUST show WordPress role "${expectedLabel}" after OIDC login; row text: ${rowText}`
          ).toBe(true);
        } finally {
          await wpAdmin.ctx.close().catch(() => {});
        }
      } finally {
        // Idempotency: only teardown when this test performed the join.
        // If biber was already a member at start, leave the membership
        // untouched.
        if (biberAddedToGroup) {
          try {
            const reqCtx = await browser.newContext({ ignoreHTTPSErrors: true });
            try {
              await shared.keycloakRemoveUserFromGroupViaRest(
                reqCtx.request,
                shared.env.keycloakBaseUrl,
                shared.env.realmName,
                shared.env.superAdminUsername,
                shared.env.superAdminPassword,
                groupPath,
                shared.env.biberUsername
              );
            } finally {
              await reqCtx.close().catch(() => {});
            }
          } catch (err) {
            console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`);
          }
        }
      }
    });
  }
};
