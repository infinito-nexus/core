const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const env = {
  keycloakBaseUrl: normalizeBaseUrl(decodeDotenvQuotedValue(process.env.KEYCLOAK_BASE_URL) || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  adminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM),
  adminClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  administratorGroupPath: decodeDotenvQuotedValue(process.env.RBAC_ADMINISTRATOR_GROUP_PATH),
  ldapCacheTtlSeconds: Number(decodeDotenvQuotedValue(process.env.NEXTCLOUD_LDAP_CACHE_TTL)),
};

function adminOverviewUrl(shared) {
  return new URL("settings/admin/overview", shared.env.nextcloudBaseUrl).toString();
}

async function adminOverviewStatus(page, shared) {
  const response = await gotoOnion(page, adminOverviewUrl(shared), {
    waitUntil: "domcontentloaded",
    timeout: resolveTimeout(60_000),
  }).catch(() => null);
  return response ? response.status() : 0;
}

async function logoutFromShell(page, shared) {
  await gotoOnion(page, shared.env.nextcloudBaseUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
  await shared.waitForVisibleCandidate(
    page,
    shared.getNextcloudShellCandidates(page),
    resolveTimeout(60_000),
    "Timed out waiting for the signed-in Nextcloud shell before logging out",
  );
  await shared.logoutStandaloneNextcloud(page);
}

exports.register = function (shared) {
  test("rbac: biber without the administrator role is refused the Nextcloud administration settings", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const biberPage = await biberContext.newPage();
    try {
      await shared.loginToStandaloneNextcloud(biberPage, shared.env.biberUsername, shared.env.biberPassword);
      expect(
        await adminOverviewStatus(biberPage, shared),
        "a realm user outside the administrator role group must not reach the Nextcloud administration settings",
      ).toBe(403);
      await logoutFromShell(biberPage, shared);
    } finally {
      await biberContext.close().catch(() => {});
    }
  });

  test("rbac: membership in the administrator group grants biber the Nextcloud administration settings", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    expect(env.ldapCacheTtlSeconds, "NEXTCLOUD_LDAP_CACHE_TTL must be a number of seconds").toBeGreaterThan(0);
    const promotionBudgetMs = (env.ldapCacheTtlSeconds + 90) * 1000;
    test.setTimeout(promotionBudgetMs + resolveTimeout(240_000));
    const adminOpts = { adminRealm: env.adminRealm, adminClientId: env.adminClientId };
    const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
    let joined = false;
    try {
      joined = await keycloakAdminAddUserToGroup(
        adminContext.request,
        env.keycloakBaseUrl,
        env.realmName,
        env.administratorGroupPath,
        shared.env.biberUsername,
        env.superAdminUsername,
        env.superAdminPassword,
        adminOpts,
      );
      const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
      const biberPage = await biberContext.newPage();
      try {
        await shared.loginToStandaloneNextcloud(biberPage, shared.env.biberUsername, shared.env.biberPassword);
        await expect
          .poll(() => adminOverviewStatus(biberPage, shared), {
            timeout: promotionBudgetMs,
            intervals: [5_000],
            message: `biber in ${env.administratorGroupPath} must reach the Nextcloud administration settings`,
          })
          .toBe(200);
        await expect(
          biberPage.locator('a[href*="/settings/admin/"]').first(),
          "the administration settings navigation must render for a member of the administrator role group",
        ).toBeVisible({ timeout: resolveTimeout(30_000) });
        await logoutFromShell(biberPage, shared);
      } finally {
        await biberContext.close().catch(() => {});
      }
    } finally {
      if (joined) {
        await keycloakRemoveUserFromGroupViaRest(
          adminContext.request,
          env.keycloakBaseUrl,
          env.realmName,
          env.superAdminUsername,
          env.superAdminPassword,
          env.administratorGroupPath,
          shared.env.biberUsername,
          adminOpts,
        ).catch((err) => console.warn(`Cleanup removal of biber from ${env.administratorGroupPath} failed: ${err}`));
      }
      await adminContext.close().catch(() => {});
    }
  });
};
