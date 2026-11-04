const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  clickOidcLoginLink,
  gotoOnion,
  installCspViolationObserver,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeUrl,
  performKeycloakLogin,
  readEnv,
} = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const RBAC_ROLE_GRANTS = [
  { groupEnv: "MASTODON_RBAC_MODERATOR_GROUP", groupPath: readEnv("MASTODON_RBAC_MODERATOR_GROUP"), roleName: "Moderator" },
  { groupEnv: "MASTODON_RBAC_ADMINISTRATOR_GROUP", groupPath: readEnv("MASTODON_RBAC_ADMINISTRATOR_GROUP"), roleName: "Admin" },
];

function env() {
  return {
    appBaseUrl: normalizeUrl(process.env.APP_BASE_URL),
    canonicalDomain: readEnv("CANONICAL_DOMAIN"),
    groupsScope: readEnv("MASTODON_OIDC_GROUPS_SCOPE"),
    keycloakBaseUrl: normalizeUrl(process.env.KEYCLOAK_BASE_URL),
    realmName: readEnv("KEYCLOAK_REALM_NAME"),
    superAdminUsername: readEnv("SUPER_ADMIN_USERNAME"),
    superAdminPassword: readEnv("SUPER_ADMIN_PASSWORD"),
    adminUsername: readEnv("ADMIN_USERNAME"),
    adminPassword: readEnv("ADMIN_PASSWORD"),
    biberUsername: readEnv("BIBER_USERNAME"),
    biberPassword: readEnv("BIBER_PASSWORD"),
  };
}

/**
 * Args:
 *   browser: the Playwright browser.
 *   username: the persona's Keycloak login.
 *   password: the persona's Keycloak password.
 * Returns the name of the Mastodon user role the session carries, "" for none.
 */
async function signInAndReadRole(browser, username, password) {
  const { appBaseUrl, canonicalDomain, groupsScope } = env();
  expect(groupsScope, "MASTODON_OIDC_GROUPS_SCOPE must be set").toBeTruthy();
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await context.newPage();
    await installCspViolationObserver(page);
    await gotoOnion(page, `${appBaseUrl}/auth/sign_in`, { waitUntil: "domcontentloaded" });
    if (!page.url().includes("openid-connect/auth")) {
      const strictLogin = page.getByRole("link", { name: /^\s*(log\s*in|sign\s*in|sso)\s*$/i }).first();
      const looseLogin = page.getByRole("link", { name: /log\s*in|sign\s*in|sso/i }).first();
      const authPage = await clickOidcLoginLink(page, strictLogin, looseLogin);
      expect(authPage, "expected the Mastodon sign-in to hand off to Keycloak").toBeTruthy();
    }
    const requestedScopes = (new URL(page.url()).searchParams.get("scope") || "").split(/[\s+]+/);
    expect(requestedScopes, "expected the Mastodon authorize request to ask for the groups scope").toContain(groupsScope);
    await performKeycloakLogin(page, username, password, canonicalDomain);
    await gotoOnion(page, `${appBaseUrl}/home`, { waitUntil: "domcontentloaded" });
    const initialState = page.locator("script#initial-state");
    await expect(initialState, "expected the signed-in web app to embed its initial state").toBeAttached({
      timeout: resolveTimeout(60_000),
    });
    const state = JSON.parse((await initialState.textContent()) || "{}");
    expect(state.meta && state.meta.me, `expected ${username} to hold a Mastodon session`).toBeTruthy();
    return (state.role && state.role.name) || "";
  } finally {
    await context.clearCookies().catch(() => {});
    await context.close().catch(() => {});
  }
}

test("administrator: the platform administrator keeps the Mastodon Owner role", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));
  const { adminUsername, adminPassword } = env();
  expect(await signInAndReadRole(browser, adminUsername, adminPassword)).toBe("Owner");
});

for (const { groupEnv, groupPath, roleName } of RBAC_ROLE_GRANTS) {
  test(`biber: the ${roleName} role follows the Keycloak role group on every login`, async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(300_000));
    const cfg = env();
    expect(groupPath, `${groupEnv} must be set`).toBeTruthy();

    const requestContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const { request } = requestContext;
    let joined = false;
    try {
      joined = await keycloakAdminAddUserToGroup(
        request,
        cfg.keycloakBaseUrl,
        cfg.realmName,
        groupPath,
        cfg.biberUsername,
        cfg.superAdminUsername,
        cfg.superAdminPassword,
      );
      expect(
        await signInAndReadRole(browser, cfg.biberUsername, cfg.biberPassword),
        `expected ${groupPath} to grant biber the Mastodon ${roleName} role`,
      ).toBe(roleName);

      if (joined) {
        await keycloakRemoveUserFromGroupViaRest(
          request,
          cfg.keycloakBaseUrl,
          cfg.realmName,
          cfg.superAdminUsername,
          cfg.superAdminPassword,
          groupPath,
          cfg.biberUsername,
        );
        joined = false;
        expect(
          await signInAndReadRole(browser, cfg.biberUsername, cfg.biberPassword),
          `expected leaving ${groupPath} to take the Mastodon ${roleName} role back from biber`,
        ).toBe("");
      }
    } finally {
      if (joined) {
        await keycloakRemoveUserFromGroupViaRest(
          request,
          cfg.keycloakBaseUrl,
          cfg.realmName,
          cfg.superAdminUsername,
          cfg.superAdminPassword,
          groupPath,
          cfg.biberUsername,
        ).catch((err) => console.warn(`Removing biber from ${groupPath} failed: ${err}`));
      }
      await requestContext.close().catch(() => {});
    }
  });
}
