const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const env = {
  baseUrl: normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL")).replace(/\/$/, ""),
  organizerSlug: decodeDotenvQuotedValue(process.env.ORGANIZER_SLUG),
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  adminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM),
  adminClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  organizerGroupPath: decodeDotenvQuotedValue(process.env.RBAC_ORGANIZER_GROUP_PATH),
  checkinGroupPath: decodeDotenvQuotedValue(process.env.RBAC_CHECKIN_GROUP_PATH),
};

async function withBiberInGroup(browser, groupPath, body) {
  const adminOpts = { adminRealm: env.adminRealm, adminClientId: env.adminClientId };
  const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
  let joined = false;
  try {
    joined = await keycloakAdminAddUserToGroup(
      adminCtx.request,
      env.keycloakBaseUrl,
      env.realmName,
      groupPath,
      env.biberUsername,
      env.superAdminUsername,
      env.superAdminPassword,
      adminOpts,
    );
    await body();
  } finally {
    if (joined) {
      await keycloakRemoveUserFromGroupViaRest(
        adminCtx.request,
        env.keycloakBaseUrl,
        env.realmName,
        env.superAdminUsername,
        env.superAdminPassword,
        groupPath,
        env.biberUsername,
        adminOpts,
      ).catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
    }
    await adminCtx.close().catch(() => {});
  }
}

async function withBiberControlSession(browser, body) {
  await withControlSession(browser, env.biberUsername, env.biberPassword, body);
}

async function withControlSession(browser, username, password, body) {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await ctx.newPage();
    await gotoOnion(page, `${env.baseUrl}/control/login`, { waitUntil: "domcontentloaded" });
    const oidcLink = page.locator("a[href*='openid-connect/auth' i], a[href*='oidc' i]").first();
    await expect(oidcLink, "the pretix-oidc login affordance must be offered on /control/login").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    await oidcLink.click();
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected the redirect to Keycloak" })
      .toContain("openid-connect/auth");
    await performKeycloakLoginForm(page, username, password);
    await expect
      .poll(
        () => {
          const url = page.url();
          return url.startsWith(`${env.baseUrl}/control/`) && !url.includes("/control/login");
        },
        { timeout: resolveTimeout(90_000), message: `expected redirect back to ${env.baseUrl}/control/` },
      )
      .toBe(true);
    await expect(
      page.locator("a[href$='/control/logout']").first(),
      "the OIDC sign-in must establish a Pretix control session",
    ).toBeAttached({ timeout: resolveTimeout(30_000) });
    await body(page);
  } finally {
    await ctx.close().catch(() => {});
  }
}

async function organizerListed(page) {
  await gotoOnion(page, `${env.baseUrl}/control/organizers/`, { waitUntil: "domcontentloaded" });
  return (await page.locator(`a[href*='/control/organizer/${env.organizerSlug}/']`).count()) > 0;
}

async function organizerSettingsStatus(page) {
  const response = await page.request.get(`${env.baseUrl}/control/organizer/${env.organizerSlug}/edit`);
  return response.status();
}

async function staffSessionStatus(page) {
  const response = await page.request.get(`${env.baseUrl}/control/sudo/`);
  return new URL(response.url()).pathname === "/control/sudo/" ? response.status() : `redirected to ${response.url()}`;
}

test("rbac: biber without a Pretix role signs in but joins no organizer team", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  await withBiberControlSession(browser, async (page) => {
    expect(await organizerListed(page), "a user without a Pretix role must not see the organizer").toBe(false);
    expect([403, 404], "a user without a Pretix role must not reach the organizer settings").toContain(
      await organizerSettingsStatus(page),
    );
    expect(await staffSessionStatus(page), "a user outside the administrator role group must not get Pretix staff").toBe(403);
  });
});

test("rbac: the administrator group grants Pretix staff through pretix-oidc", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  await withControlSession(browser, env.adminUsername, env.adminPassword, async (page) => {
    expect(await staffSessionStatus(page), "the administrator role group must grant the Pretix staff admin mode").toBe(200);
  });
});

test("rbac: membership in the organizer group grants the organizer settings, leaving it revokes them", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  await withBiberInGroup(browser, env.organizerGroupPath, async () => {
    await withBiberControlSession(browser, async (page) => {
      expect(await organizerListed(page), "an organizer-group member must join the Organizers (SSO) team").toBe(true);
      expect(await organizerSettingsStatus(page), "the Organizers (SSO) team must grant the organizer settings").toBe(200);
    });
  });
  await withBiberControlSession(browser, async (page) => {
    expect(await organizerListed(page), "leaving the organizer group must remove biber from the Organizers (SSO) team at the next sign-in").toBe(false);
    expect([403, 404], "a former organizer-group member must lose the organizer settings").toContain(
      await organizerSettingsStatus(page),
    );
  });
});

test("rbac: membership in the checkin group grants check-in without the organizer settings", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  await withBiberInGroup(browser, env.checkinGroupPath, async () => {
    await withBiberControlSession(browser, async (page) => {
      expect(await organizerListed(page), "a checkin-group member must join the Check-in (SSO) team").toBe(true);
      expect(await organizerSettingsStatus(page), "the Check-in (SSO) team must not grant the organizer settings").toBe(403);
    });
  });
});
