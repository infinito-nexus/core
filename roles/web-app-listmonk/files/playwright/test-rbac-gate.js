const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminToken,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const oidcIssuerUrl = normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));
const keycloakBaseUrl = normalizeBaseUrl(decodeDotenvQuotedValue(process.env.KEYCLOAK_BASE_URL));
const keycloakRealm = decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME);
const superAdminUsername = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME);
const superAdminPassword = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD);

async function signInThroughKeycloak(page, username, password) {
  await gotoOnion(page, `${appBaseUrl}/admin/`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "the Listmonk login page must hand over to Keycloak",
    })
    .toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);
  await performKeycloakLoginForm(page, username, password);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "Keycloak must return to Listmonk",
    })
    .toContain(appBaseUrl);
}

async function usersApiStatus(page) {
  const response = await page.request.get(`${appBaseUrl}/api/users`, {
    failOnStatusCode: false,
    maxRedirects: 0,
    timeout: resolveTimeout(30_000),
  });
  return response.status();
}

async function keycloakUserOf(request, headers, username) {
  const usersUrl = `${keycloakBaseUrl}/admin/realms/${encodeURIComponent(keycloakRealm)}/users`;
  const lookup = await request.get(`${usersUrl}?username=${encodeURIComponent(username)}&exact=true`, {
    headers,
    timeout: resolveTimeout(30_000),
  });
  expect(lookup.ok(), `the Keycloak lookup of ${username} must succeed`).toBe(true);
  const match = (await lookup.json()).find((user) => user.username === username);
  expect(match, `${username} must exist in Keycloak`).toBeTruthy();
  const read = await request.get(`${usersUrl}/${match.id}`, { headers, timeout: resolveTimeout(30_000) });
  expect(read.ok(), `reading ${username} from Keycloak must succeed`).toBe(true);
  return { url: `${usersUrl}/${match.id}`, user: await read.json() };
}

exports.register = function () {
  test("rbac: Listmonk admits the administrator as Super Admin", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000));
    await signInThroughKeycloak(page, adminUsername, adminPassword);
    expect(await usersApiStatus(page), "the administrator MUST manage Listmonk users").toBe(200);
  });

  test("rbac: Listmonk refuses biber, who holds no manager or viewer role", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000));
    await signInThroughKeycloak(page, biberUsername, biberPassword);
    expect(
      await usersApiStatus(page),
      "biber holds no Listmonk role and MUST NOT get a Listmonk session",
    ).not.toBe(200);
    await gotoOnion(page, `${appBaseUrl}/admin/`, { waitUntil: "domcontentloaded" });
    await expect(
      page.locator(".b-sidebar .menu-list"),
      "biber MUST NOT reach the Listmonk dashboard",
    ).toHaveCount(0);
  });

  test("rbac: claiming the administrator's address in Keycloak does not reach the Listmonk administrator", async ({ page, request }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(240_000));
    expect(adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
    expect(keycloakBaseUrl, "KEYCLOAK_BASE_URL must be set").toBeTruthy();
    expect(keycloakRealm, "KEYCLOAK_REALM_NAME must be set").toBeTruthy();
    expect(superAdminUsername, "SUPER_ADMIN_USERNAME must be set").toBeTruthy();
    expect(superAdminPassword, "SUPER_ADMIN_PASSWORD must be set").toBeTruthy();

    const adminHeaders = async () => ({
      Authorization: `Bearer ${await keycloakAdminToken(request, keycloakBaseUrl, superAdminUsername, superAdminPassword)}`,
      "Content-Type": "application/json",
    });
    const headers = await adminHeaders();
    const biber = await keycloakUserOf(request, headers, biberUsername);
    expect(
      (biber.user.email || "").toLowerCase(),
      "biber must not hold the administrator's address before the claim",
    ).not.toBe(adminEmail.toLowerCase());

    const claim = await request.put(biber.url, {
      headers,
      data: { ...biber.user, email: adminEmail },
      timeout: resolveTimeout(30_000),
    });
    try {
      expect(claim.ok(), "Keycloak MUST refuse to give biber the administrator's address").toBe(false);
      expect(await claim.text(), "Keycloak MUST refuse the claim because of the address").toMatch(/email/i);
      const after = await keycloakUserOf(request, headers, biberUsername);
      expect(after.user.email, "the refused claim MUST leave biber's address unchanged").toBe(biber.user.email);

      await signInThroughKeycloak(page, biberUsername, biberPassword);
      expect(
        await usersApiStatus(page),
        "biber MUST NOT reach the Listmonk administrator account by claiming its address",
      ).not.toBe(200);
    } finally {
      if (claim.ok()) {
        const restore = await request.put(biber.url, {
          headers: await adminHeaders(),
          data: biber.user,
          timeout: resolveTimeout(30_000),
        });
        expect(restore.ok(), "biber's address must be restored after an accepted claim").toBe(true);
      }
    }
  });
};
