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
const { performKeycloakLogin } = require("./personas/utils/keycloak");
const { confirmKeycloakLogoutIfPrompted } = require("./personas/utils/logout");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { dismissFirstRunWizard } = require("./test-admin-native");

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const keycloakBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.KEYCLOAK_BASE_URL, "KEYCLOAK_BASE_URL"));
const realmName = requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME");
const superAdminUsername = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME || "");
const superAdminPassword = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD || "");
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const biberUsername = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
const biberPassword = requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD");
const editorGroup = decodeDotenvQuotedValue(process.env.RBAC_GROUP_EDITOR || "");
const editorRoleName = requireDotenvValue(process.env.SHOPWARE_EDITOR_ROLE_NAME, "SHOPWARE_EDITOR_ROLE_NAME");

async function bearerToken(page) {
  let cookie = null;
  await expect
    .poll(
      async () => {
        cookie = (await page.context().cookies()).find((c) => c.name === "bearerAuth") || null;
        return cookie !== null;
      },
      {
        message: "the administration stores its API token in the bearerAuth cookie once the one-time token exchange of AdminOpenAuth lands",
        timeout: resolveTimeout(60_000),
      },
    )
    .toBe(true);
  const auth = JSON.parse(decodeURIComponent(cookie.value));
  expect(auth.access, "the bearerAuth cookie must carry an access token").toBeTruthy();
  return auth.access;
}

async function submitKeycloakSignIn(page, username, password) {
  expect(username, "username must be set").toBeTruthy();
  expect(password, "password must be set").toBeTruthy();

  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/admin`, { waitUntil: "domcontentloaded" });
  const ssoButton = page
    .locator("a.heptacom-admin-open-auth--button")
    .filter({ hasText: /keycloak/i })
    .first();
  await expect(ssoButton, "AdminOpenAuth must offer the Keycloak provider on the login form").toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  const callback = page.waitForResponse((response) => /\/open-auth\/[^/]+\/redirect$/.test(new URL(response.url()).pathname), {
    timeout: resolveTimeout(120_000),
  });
  callback.catch(() => {});
  await ssoButton.click();
  await performKeycloakLogin(page, username, password, canonicalDomain);
  return callback;
}

async function signInThroughKeycloak(page, username, password) {
  const callback = await submitKeycloakSignIn(page, username, password);
  expect(callback.status(), "the AdminOpenAuth callback must admit a role-group member").toBe(303);

  const token = await bearerToken(page);
  const response = await page.request.get(`${appBaseUrl}/api/_info/me`, {
    headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
  });
  expect(response.status(), "/api/_info/me must answer for every signed-in user").toBe(200);
  const body = await response.json();
  return body.data.attributes || body.data;
}

async function signOut(page) {
  await dismissFirstRunWizard(page);
  const toggle = page.locator(".sw-admin-menu__user-actions-toggle");
  const clicked = await toggle
    .click({ timeout: resolveTimeout(30_000) })
    .then(() => page.locator(".sw-admin-menu__logout-action").click({ timeout: resolveTimeout(15_000) }))
    .then(() => true)
    .catch(() => false);
  if (clicked) {
    await confirmKeycloakLogoutIfPrompted(page);
  }
  await page.context().clearCookies();
}

function aclRoleNames(user) {
  return (user.aclRoles || []).map((role) => (role.attributes || role).name);
}

test.describe.serial("shopware RBAC through the Keycloak groups claim", () => {
  test("biber: Keycloak sign-in without a Shopware group is refused before an account is created", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000)); // Keycloak round-trip plus the refused callback

    const callback = await submitKeycloakSignIn(page, biberUsername, biberPassword);
    expect(callback.status(), "the AdminOpenAuth role gate must refuse a user outside every Shopware group").toBe(403);
    expect(
      (await page.context().cookies()).some((cookie) => cookie.name === "bearerAuth"),
      "a refused sign-in must not leave an administration token",
    ).toBe(false);
    await page.context().clearCookies();
  });

  test("biber: editor group membership grants the Editor ACL role", async ({ page, browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(240_000)); // group join, Keycloak round-trip and group teardown
    expect(editorGroup, "RBAC_GROUP_EDITOR must be set").toBeTruthy();
    expect(superAdminUsername, "SUPER_ADMIN_USERNAME must be set").toBeTruthy();
    expect(superAdminPassword, "SUPER_ADMIN_PASSWORD must be set").toBeTruthy();

    const admin = await browser.newContext({ ignoreHTTPSErrors: true });
    let joined = false;
    try {
      joined = await keycloakAdminAddUserToGroup(
        admin.request,
        keycloakBaseUrl,
        realmName,
        editorGroup,
        biberUsername,
        superAdminUsername,
        superAdminPassword,
      );

      const user = await signInThroughKeycloak(page, biberUsername, biberPassword);
      try {
        expect(user.admin, "the editor group must not grant the admin flag").toBe(false);
        expect(aclRoleNames(user), `members of ${editorGroup} must hold the ${editorRoleName} ACL role`).toContain(
          editorRoleName,
        );
      } finally {
        await signOut(page);
      }
    } finally {
      if (joined) {
        await keycloakRemoveUserFromGroupViaRest(
          admin.request,
          keycloakBaseUrl,
          realmName,
          superAdminUsername,
          superAdminPassword,
          editorGroup,
          biberUsername,
        ).catch((err) => console.warn(`Cleanup removal of biber from ${editorGroup} failed: ${err}`));
      }
      await admin.close().catch(() => {});
    }
  });

  test("administrator: administrator group membership keeps the Shopware admin flag", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000)); // Keycloak round-trip plus the first-run wizard probe

    const user = await signInThroughKeycloak(page, adminUsername, adminPassword);
    try {
      expect(user.admin, "members of the administrator group must hold the Shopware admin flag after sign-in").toBe(true);
    } finally {
      await signOut(page);
    }
  });

  test("administrator: the Editor ACL role holds every privilege the administration expands its permission keys to", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000)); // Keycloak round-trip plus the administration boot that registers the privilege mappings

    await signInThroughKeycloak(page, adminUsername, adminPassword);
    try {
      const token = await bearerToken(page);
      const response = await page.request.post(`${appBaseUrl}/api/search/acl-role`, {
        headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
        data: { filter: [{ type: "equals", field: "name", value: editorRoleName }], limit: 1 },
      });
      expect(response.status(), "the administrator must read the ACL roles").toBe(200);
      const role = ((await response.json()).data || [])[0];
      expect(role, `the ${editorRoleName} ACL role must exist`).toBeTruthy();
      const deployed = (role.attributes || role).privileges || [];
      const adminKeys = deployed.filter((privilege) => /^[a-z_]+\.(viewer|editor|creator|deleter)$/.test(privilege));
      expect(adminKeys.length, `the ${editorRoleName} ACL role must name its administration permission keys`).toBeGreaterThan(0);

      let expanded = [];
      await expect
        .poll(
          async () => {
            expanded = await page.evaluate(
              (keys) => (window.Shopware ? window.Shopware.Service("privileges").getPrivilegesForAdminPrivilegeKeys(keys) : []),
              adminKeys,
            );
            return expanded.length > adminKeys.length;
          },
          { message: "the administration registers its privilege mappings once its modules booted", timeout: resolveTimeout(60_000) },
        )
        .toBe(true);
      const missing = expanded.filter((privilege) => !deployed.includes(privilege));
      expect(
        missing,
        `SHOPWARE_ACL_EDITOR_PRIVILEGES in vars/main.yml lags behind this Shopware version; add: ${missing.join(", ")}`,
      ).toEqual([]);
    } finally {
      await signOut(page);
    }
  });
});
