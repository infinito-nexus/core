const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { keycloakAdminAddUserToGroup, keycloakRemoveUserFromGroupViaRest } = require("./personas");

const CLEANUP_DEADLINE_MS = 30_000;

function withDeadline(promise, label) {
  return Promise.race([
    promise,
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error(`${label} exceeded ${CLEANUP_DEADLINE_MS} ms`)), resolveTimeout(CLEANUP_DEADLINE_MS)),
    ),
  ]);
}

async function administratorFlagAfterSignIn(browser, shared, signIn, username, password, label) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await context.newPage();
    await page.setViewportSize({ width: 1440, height: 1100 });
    await signIn(page, username, password, label);
    const isAdministrator = await shared.sessionIsAdministrator(page, label);
    await shared.logout(page, label);
    return isAdministrator;
  } finally {
    await context.close().catch(() => {});
  }
}

exports.register = function (shared) {
  test("rbac: the administrator group grants biber the Jellyfin administrator flag over OIDC and leaving it revokes the flag", async ({ browser }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(300_000));
    const { env } = shared;
    expect(env.adminGroupPath, "JELLYFIN_ADMIN_GROUP_PATH must be set").toBeTruthy();
    expect(env.keycloakBaseUrl, "KEYCLOAK_BASE_URL must be set").toBeTruthy();
    expect(env.keycloakRealm, "KEYCLOAK_REALM_NAME must be set").toBeTruthy();
    expect(env.keycloakAdminUsername, "KEYCLOAK_ADMIN_USERNAME must be set").toBeTruthy();
    expect(env.keycloakAdminPassword, "KEYCLOAK_ADMIN_PASSWORD must be set").toBeTruthy();
    expect(env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    const keycloak = await browser.newContext({ ignoreHTTPSErrors: true });
    let joined = false;
    try {
      joined = await keycloakAdminAddUserToGroup(
        keycloak.request,
        env.keycloakBaseUrl,
        env.keycloakRealm,
        env.adminGroupPath,
        env.biberUsername,
        env.keycloakAdminUsername,
        env.keycloakAdminPassword,
      );
      expect(
        await administratorFlagAfterSignIn(browser, shared, shared.signInViaOidc, env.biberUsername, env.biberPassword, "biber-oidc-administrator"),
        `biber in ${env.adminGroupPath} must sign in over OIDC as Jellyfin administrator`,
      ).toBe(true);
    } finally {
      if (joined) {
        await withDeadline(
          keycloakRemoveUserFromGroupViaRest(
            keycloak.request,
            env.keycloakBaseUrl,
            env.keycloakRealm,
            env.keycloakAdminUsername,
            env.keycloakAdminPassword,
            env.adminGroupPath,
            env.biberUsername,
          ),
          `removing biber from ${env.adminGroupPath}`,
        ).catch((err) => console.warn(`Cleanup removal of biber from ${env.adminGroupPath} failed: ${err}`));
      }
      await keycloak.close().catch(() => {});
    }

    if (joined) {
      expect(
        await administratorFlagAfterSignIn(browser, shared, shared.signInViaOidc, env.biberUsername, env.biberPassword, "biber-oidc-user"),
        `biber outside ${env.adminGroupPath} must sign in over OIDC without the Jellyfin administrator flag`,
      ).toBe(false);
    }
  });

  test("administrator: the LDAP admin filter signs the administrator group member in as Jellyfin administrator and biber without the flag", async ({ browser }) => {
    shared.skipUnlessServiceEnabled("ldap");
    shared.skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(180_000));
    const { env } = shared;
    expect(env.ldapAdminUsername, "LDAP_ADMIN_USERNAME must be set").toBeTruthy();
    expect(env.ldapAdminPassword, "LDAP_ADMIN_PASSWORD must be set").toBeTruthy();
    expect(env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    expect(
      await administratorFlagAfterSignIn(browser, shared, shared.signInViaLdap, env.ldapAdminUsername, env.ldapAdminPassword, "administrator-ldap"),
      `${env.ldapAdminUsername}, a member of the administrator group in the directory, must sign in over LDAP as Jellyfin administrator`,
    ).toBe(true);
    expect(
      await administratorFlagAfterSignIn(browser, shared, shared.signInViaLdap, env.biberUsername, env.biberPassword, "biber-ldap-user"),
      "biber outside the administrator group must sign in over LDAP without the Jellyfin administrator flag",
    ).toBe(false);
  });
};
