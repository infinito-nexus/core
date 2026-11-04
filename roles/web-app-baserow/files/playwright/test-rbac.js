const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  assertUnauthenticatedLanding,
  decodeDotenvQuotedValue,
  gotoOnion,
  inAppLogout,
  normalizeBaseUrl,
  performKeycloakLoginExpectingDenial,
  performKeycloakLoginForm,
} = require("./personas");
const keycloakAdmin = require("./personas/utils/keycloak");

const env = {
  baseUrl: normalizeBaseUrl(process.env.BASEROW_BASE_URL),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN),
  oidcIssuerUrl: normalizeBaseUrl(process.env.OIDC_ISSUER_URL),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  biberFullName: decodeDotenvQuotedValue(process.env.BIBER_FULL_NAME),
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  keycloakAdminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM),
  keycloakAdminCliClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  adminGroupPath: decodeDotenvQuotedValue(process.env.RBAC_ADMIN_GROUP_PATH),
  userGroupPath: decodeDotenvQuotedValue(process.env.RBAC_USER_GROUP_PATH),
};

test.use({ ignoreHTTPSErrors: true });

function withDeadline(promise, ms, label) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} exceeded ${ms} ms`)), ms);
  });
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
}

function adminOpts() {
  return { adminRealm: env.keycloakAdminRealm, adminClientId: env.keycloakAdminCliClientId };
}

function addToGroup(request, username, groupPath) {
  return keycloakAdmin.keycloakAdminAddUserToGroup(
    request,
    env.keycloakBaseUrl,
    env.realmName,
    groupPath,
    username,
    env.superAdminUsername,
    env.superAdminPassword,
    adminOpts()
  );
}

function removeFromGroup(request, username, groupPath) {
  return keycloakAdmin.keycloakRemoveUserFromGroupViaRest(
    request,
    env.keycloakBaseUrl,
    env.realmName,
    env.superAdminUsername,
    env.superAdminPassword,
    groupPath,
    username,
    adminOpts()
  );
}

async function withUserInGroup(browser, username, groupPath, fn) {
  const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
  let added = false;
  try {
    added = await addToGroup(adminCtx.request, username, groupPath);
    return await fn();
  } finally {
    if (added) {
      await withDeadline(
        removeFromGroup(adminCtx.request, username, groupPath),
        resolveTimeout(30_000),
        `Removing ${username} from ${groupPath}`
      ).catch((err) => console.warn(`Cleanup removal of ${username} from ${groupPath} failed: ${err}`));
    }
    await adminCtx.close().catch(() => {});
  }
}

async function withUserOutOfGroup(browser, username, groupPath, fn) {
  const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
  let wasMember = false;
  try {
    wasMember = !(await addToGroup(adminCtx.request, username, groupPath));
    await removeFromGroup(adminCtx.request, username, groupPath);
    return await fn();
  } finally {
    if (wasMember) {
      await withDeadline(
        addToGroup(adminCtx.request, username, groupPath),
        resolveTimeout(30_000),
        `Restoring ${username} in ${groupPath}`
      ).catch((err) => console.warn(`Cleanup restore of ${username} in ${groupPath} failed: ${err}`));
    }
    await adminCtx.close().catch(() => {});
  }
}

function withBiberInGroup(browser, groupPath, fn) {
  return withUserInGroup(browser, env.biberUsername, groupPath, fn);
}

async function reachKeycloak(page) {
  await page.context().clearCookies();
  await gotoOnion(page, `${env.baseUrl}/`);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "Expected the oauth2-proxy gate to send an anonymous visitor to Keycloak",
    })
    .toContain(`${env.oidcIssuerUrl}/protocol/openid-connect/auth`);
}

async function signIn(page, username, password) {
  await reachKeycloak(page);
  await performKeycloakLoginForm(page, username, password);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(90_000),
      message: `Expected ${username} to land back on ${env.baseUrl}`,
    })
    .toContain(env.baseUrl);
  await expect(page.locator(".sidebar").first(), `Expected the authenticated Baserow shell for ${username}`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
}

async function bridgePayload(page) {
  const response = await page.request.get(`${env.baseUrl}/api/infinito/sso/token/`, { timeout: resolveTimeout(30_000) });
  const body = await response.text();
  expect(response.ok(), `The trusted-header bridge answered ${response.status()}: ${body.slice(0, 200)}`).toBe(true);
  const payload = JSON.parse(body);
  expect(payload.user, "The trusted-header bridge MUST return the Baserow user").toBeTruthy();
  return payload;
}

async function bridgeUser(page) {
  return (await bridgePayload(page)).user;
}

async function setBaserowLanguage(page, accessToken, language) {
  const response = await page.request.patch(`${env.baseUrl}/api/user/account/`, {
    headers: { Authorization: `JWT ${accessToken}`, "Content-Type": "application/json" },
    data: { language },
    timeout: resolveTimeout(30_000),
  });
  expect(response.ok(), `Restoring the Baserow language answered ${response.status()}`).toBe(true);
}

async function signOut(page) {
  await inAppLogout(page);
  await assertUnauthenticatedLanding(page, env.baseUrl);
}

test("biber: oauth2 gate refuses baserow without a baserow role group", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));

  await reachKeycloak(page);
  await performKeycloakLoginExpectingDenial(page, env.biberUsername, env.biberPassword, env.canonicalDomain);
  const cookies = await page.context().cookies(env.baseUrl);
  expect(
    cookies.some((cookie) => cookie.name === "jwt_token"),
    "A user outside every Baserow role group MUST NOT receive a Baserow session"
  ).toBe(false);
});

test("biber: user role group admits baserow without staff", async ({ browser, page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(240_000));

  await withBiberInGroup(browser, env.userGroupPath, async () => {
    await signIn(page, env.biberUsername, env.biberPassword);
    const user = await bridgeUser(page);
    expect(user.is_staff, `${env.userGroupPath} MUST NOT grant Baserow staff`).toBe(false);
    await signOut(page);
  });
});

test("biber: administrator role group grants baserow staff and leaving it revokes staff", async ({
  browser,
  page,
}) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(420_000));

  await withBiberInGroup(browser, env.adminGroupPath, async () => {
    await signIn(page, env.biberUsername, env.biberPassword);
    expect((await bridgeUser(page)).is_staff, `${env.adminGroupPath} MUST grant Baserow staff`).toBe(true);
    await signOut(page);
  });

  await withBiberInGroup(browser, env.userGroupPath, async () => {
    await signIn(page, env.biberUsername, env.biberPassword);
    expect(
      (await bridgeUser(page)).is_staff,
      `Leaving ${env.adminGroupPath} MUST revoke Baserow staff on the next login`
    ).toBe(false);
    await signOut(page);
  });
});

test("biber: name and language follow Keycloak, and a forged name header is overwritten", async ({ browser, page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(360_000));
  expect(env.biberFullName, "BIBER_FULL_NAME must be set").toBeTruthy();

  await withBiberInGroup(browser, env.userGroupPath, async () => {
    await signIn(page, env.biberUsername, env.biberPassword);
    const storedLanguage = (await bridgeUser(page)).language;
    await signOut(page);

    const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    let previous = null;
    try {
      previous = await keycloakAdmin.keycloakAdminSetUserAttributes(
        adminCtx.request,
        env.keycloakBaseUrl,
        env.realmName,
        env.biberUsername,
        { locale: "de" },
        env.superAdminUsername,
        env.superAdminPassword,
        adminOpts()
      );
      const forged = await browser.newContext({
        ignoreHTTPSErrors: true,
        extraHTTPHeaders: { "X-Forwarded-Name": "Forged Name", "X-Forwarded-Locale": "fr" },
      });
      try {
        const forgedPage = await forged.newPage();
        await signIn(forgedPage, env.biberUsername, env.biberPassword);
        const payload = await bridgePayload(forgedPage);
        expect(payload.user.first_name, "The Baserow name MUST be the Keycloak name claim, not the header the browser sent").toBe(
          env.biberFullName
        );
        expect(payload.user.language, "The Baserow language MUST follow the Keycloak locale attribute").toBe("de");
        await setBaserowLanguage(forgedPage, payload.access_token, storedLanguage);
      } finally {
        await forged.close().catch(() => {});
      }
    } finally {
      if (previous) {
        await keycloakAdmin
          .keycloakAdminSetUserAttributes(
            adminCtx.request,
            env.keycloakBaseUrl,
            env.realmName,
            env.biberUsername,
            previous,
            env.superAdminUsername,
            env.superAdminPassword,
            adminOpts()
          )
          .catch((err) => console.warn(`Restoring biber's Keycloak locale failed: ${err}`));
      }
      await adminCtx.close().catch(() => {});
    }
  });
});

test("administrator: platform administrator keeps baserow staff", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));

  await signIn(page, env.adminUsername, env.adminPassword);
  expect((await bridgeUser(page)).is_staff, "The bootstrap administrator MUST keep Baserow staff").toBe(true);
  await signOut(page);
});

test("administrator: bootstrap administrator keeps baserow staff outside the administrator role group", async ({
  browser,
  page,
}) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(240_000));

  await withUserInGroup(browser, env.adminUsername, env.userGroupPath, () =>
    withUserOutOfGroup(browser, env.adminUsername, env.adminGroupPath, async () => {
      await signIn(page, env.adminUsername, env.adminPassword);
      const user = await bridgeUser(page);
      expect(user.is_staff, "The bootstrap administrator MUST NOT be demoted by the groups header").toBe(true);
      await signOut(page);
    })
  );
});
