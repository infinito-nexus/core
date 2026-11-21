const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const keycloakBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.KEYCLOAK_BASE_URL, "KEYCLOAK_BASE_URL"));
const realmName = requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME");
const superAdminUsername = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME || "");
const superAdminPassword = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD || "");
const userManagerGroupPath = decodeDotenvQuotedValue(process.env.RBAC_USER_MANAGER_GROUP_PATH || "");

/**
 * Args:
 *   page: Playwright page of a signed-in Decidim session.
 *   baseUrl: origin of the Decidim instance.
 *
 * Returns: "granted" when /admin/ renders the administration, "refused" for the 404 Decidim renders in place at /admin for a user without an admin role (its route constraint), otherwise "HTTP <status> at <path>".
 */
async function adminAreaAccess(page, baseUrl) {
  const response = await gotoOnion(page, `${baseUrl}/admin/`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: resolveTimeout(30_000) }).catch(() => {});
  const status = response ? response.status() : 0;
  const landedOn = new URL(page.url()).pathname;
  if (landedOn.startsWith("/admin") && response?.ok()) return "granted";
  if (landedOn.startsWith("/admin") && status === 404) return "refused";
  return `HTTP ${status} at ${landedOn}`;
}

exports.register = function (shared) {
  test("biber: user-manager role group opens the Decidim admin area and leaving it closes it", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(300_000)); // two OIDC sign-ins around a Keycloak group change
    expect(userManagerGroupPath, "RBAC_USER_MANAGER_GROUP_PATH must be set").toBeTruthy();
    expect(superAdminUsername, "SUPER_ADMIN_USERNAME must be set").toBeTruthy();
    expect(superAdminPassword, "SUPER_ADMIN_PASSWORD must be set").toBeTruthy();

    const signInAsBiber = async () => {
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      const page = await context.newPage();
      await shared.oidcLogin(page, shared.env.biberUsername, shared.env.biberPassword);
      await expect(page, "biber MUST hold a Decidim session after the OIDC login").not.toHaveURL(/sign_in/);
      return { context, page };
    };

    const admin = await browser.newContext({ ignoreHTTPSErrors: true });
    let joined = false;
    try {
      joined = await keycloakAdminAddUserToGroup(
        admin.request,
        keycloakBaseUrl,
        realmName,
        userManagerGroupPath,
        shared.env.biberUsername,
        superAdminUsername,
        superAdminPassword,
      );
      const promoted = await signInAsBiber();
      try {
        expect(
          await adminAreaAccess(promoted.page, shared.env.baseUrl),
          "the user-manager group MUST grant the user_manager role on the OIDC login",
        ).toBe("granted");
      } finally {
        await promoted.context.close().catch(() => {});
      }
    } finally {
      if (joined) {
        try {
          await Promise.race([
            keycloakRemoveUserFromGroupViaRest(
              admin.request,
              keycloakBaseUrl,
              realmName,
              superAdminUsername,
              superAdminPassword,
              userManagerGroupPath,
              shared.env.biberUsername,
            ),
            new Promise((_, reject) => setTimeout(() => reject(new Error("group cleanup timed out")), 30_000)),
          ]);
        } catch (err) {
          console.warn(`Cleanup removal of biber from ${userManagerGroupPath} failed: ${err}`);
        }
      }
      await admin.close().catch(() => {});
    }

    const demoted = await signInAsBiber();
    try {
      expect(
        await adminAreaAccess(demoted.page, shared.env.baseUrl),
        "leaving the user-manager group MUST revoke the user_manager role on the next OIDC login",
      ).toBe("refused");
    } finally {
      await demoted.context.close().catch(() => {});
    }
  });
};
