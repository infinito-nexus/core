const { test, expect } = require("@playwright/test");
const { resolveTimeout, isSplitRealmOidc } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakAdminSetUserAttributes,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  performKeycloakLogin,
} = require("./personas");

const env = {
  base: normalizeBaseUrl(process.env.APP_BASE_URL || ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN),
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  administratorGroupPath: decodeDotenvQuotedValue(process.env.RBAC_ADMINISTRATOR_GROUP_PATH),
};

const ADMIN_PATH = "/bin/admin/XWiki/XWikiPreferences";
const USER_REFERENCE = /^(?:[^:]+:)?XWiki\./;
const CLEANUP_DEADLINE_MS = 30_000;

function gateOidc() {
  skipUnlessServiceEnabled("sso");
  test.skip(isSplitRealmOidc(), "clearnet app with an onion OIDC issuer: unreachable from one browser");
  for (const [name, value] of Object.entries(env)) {
    expect(value, `${name} must be set`).toBeTruthy();
  }
}

function withDeadline(promise, label) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} exceeded its deadline`)), resolveTimeout(CLEANUP_DEADLINE_MS));
  });
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
}

async function withPage(browser, body) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    return await body(await context.newPage());
  } finally {
    await context.close().catch(() => {});
  }
}

async function signInViaOidc(page, username, password) {
  await gotoOnion(page, `${env.base}/bin/login/XWiki/XWikiLogin`, { waitUntil: "domcontentloaded" });
  await page.waitForURL(/\/protocol\/openid-connect\/auth/, { timeout: resolveTimeout(45_000) });
  await performKeycloakLogin(page, username, password, env.canonicalDomain);
}

async function adminPageStatus(page) {
  const response = await gotoOnion(page, `${env.base}${ADMIN_PATH}`, { waitUntil: "domcontentloaded" });
  expect(response, `Expected a response for ${ADMIN_PATH}`).toBeTruthy();
  return response.status();
}

test("oidc: the XWiki authorize request asks for the phone and address scopes", async ({ page }) => {
  gateOidc();
  await gotoOnion(page, `${env.base}/bin/login/XWiki/XWikiLogin`, { waitUntil: "domcontentloaded" });
  await page.waitForURL(/\/protocol\/openid-connect\/auth/, { timeout: resolveTimeout(45_000) });
  const scopes = (new URL(page.url()).searchParams.get("scope") || "").split(/\s+/);
  expect(scopes, `the authorize request MUST carry phone and address, got ${page.url()}`).toEqual(
    expect.arrayContaining(["openid", "phone", "address"]),
  );
});

test("biber: administrator group membership maps onto XWikiAdminGroup at OIDC login", async ({ browser }) => {
  gateOidc();
  test.setTimeout(resolveTimeout(300_000));

  const api = await browser.newContext({ ignoreHTTPSErrors: true });
  let joined = false;
  try {
    joined = await keycloakAdminAddUserToGroup(
      api.request,
      env.keycloakBaseUrl,
      env.realmName,
      env.administratorGroupPath,
      env.biberUsername,
      env.superAdminUsername,
      env.superAdminPassword,
    );

    await withPage(browser, async (page) => {
      await signInViaOidc(page, env.biberUsername, env.biberPassword);
      expect(
        await adminPageStatus(page),
        `${env.biberUsername} holds ${env.administratorGroupPath}, so ${ADMIN_PATH} MUST open after the OIDC login`,
      ).toBeLessThan(400);
      await expect(page).toHaveURL(new RegExp(ADMIN_PATH.replace(/\//g, "\\/")));
    });

    if (joined) {
      await keycloakRemoveUserFromGroupViaRest(
        api.request,
        env.keycloakBaseUrl,
        env.realmName,
        env.superAdminUsername,
        env.superAdminPassword,
        env.administratorGroupPath,
        env.biberUsername,
      );
      joined = false;

      await withPage(browser, async (page) => {
        await signInViaOidc(page, env.biberUsername, env.biberPassword);
        expect(
          await adminPageStatus(page),
          `${env.biberUsername} left ${env.administratorGroupPath}, so the OIDC login MUST drop XWikiAdminGroup and ${ADMIN_PATH} MUST answer 403`,
        ).toBe(403);
      });
    }
  } finally {
    if (joined) {
      await withDeadline(
        keycloakRemoveUserFromGroupViaRest(
          api.request,
          env.keycloakBaseUrl,
          env.realmName,
          env.superAdminUsername,
          env.superAdminPassword,
          env.administratorGroupPath,
          env.biberUsername,
        ),
        "group cleanup",
      ).catch((err) => console.warn(`Cleanup removal of ${env.biberUsername} from ${env.administratorGroupPath} failed: ${err}`));
    }
    await api.close().catch(() => {});
  }
});

test("biber: the Keycloak phone number and postal address reach the XWiki profile at OIDC login", async ({ browser }) => {
  gateOidc();
  test.setTimeout(resolveTimeout(240_000));

  const suffix = String(Date.now()).slice(-7);
  const phone = `+49 30 ${suffix}`;
  const street = `Claimstrasse ${suffix}`;
  const postalCode = suffix.slice(0, 5);
  const locality = `Berlin ${suffix}`;
  const api = await browser.newContext({ ignoreHTTPSErrors: true });
  let previous = null;
  try {
    previous = await keycloakAdminSetUserAttributes(
      api.request,
      env.keycloakBaseUrl,
      env.realmName,
      env.biberUsername,
      { phoneNumber: phone, street, postal_code: postalCode, locality, country: "DE" },
      env.superAdminUsername,
      env.superAdminPassword,
    );

    await withPage(browser, async (page) => {
      await signInViaOidc(page, env.biberUsername, env.biberPassword);
      await gotoOnion(page, `${env.base}/bin/view/Main/`, { waitUntil: "domcontentloaded" });
      const reference = await page.locator("html").getAttribute("data-xwiki-user-reference");
      expect(reference, "XWiki MUST render the signed-in user reference on <html> after the OIDC login").toMatch(
        USER_REFERENCE,
      );
      const profilePage = reference.replace(USER_REFERENCE, "");
      await gotoOnion(page, `${env.base}/bin/view/XWiki/${encodeURIComponent(profilePage)}`, {
        waitUntil: "domcontentloaded",
      });
      await expect(
        page.locator("body"),
        `the phone_number claim MUST land in the phone field of XWiki.${profilePage}`,
      ).toContainText(phone, { timeout: resolveTimeout(30_000) });
      await expect(
        page.locator("body"),
        `oidc.user.mapping MUST compose the street_address member into the address field of XWiki.${profilePage}`,
      ).toContainText(street);
      await expect(
        page.locator("body"),
        `oidc.user.mapping MUST compose the postal_code and locality members into the address field of XWiki.${profilePage}`,
      ).toContainText(`${postalCode} ${locality}`);
    });
  } finally {
    if (previous) {
      await withDeadline(
        keycloakAdminSetUserAttributes(
          api.request,
          env.keycloakBaseUrl,
          env.realmName,
          env.biberUsername,
          previous,
          env.superAdminUsername,
          env.superAdminPassword,
        ),
        "attribute restore",
      ).catch((err) => console.warn(`Restoring the Keycloak attributes of ${env.biberUsername} failed: ${err}`));
    }
    await api.close().catch(() => {});
  }
});
