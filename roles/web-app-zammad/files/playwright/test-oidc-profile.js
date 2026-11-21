const { test, expect, request } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");
const keycloakAdmin = require("./personas/utils/keycloak");

const keycloak = {
  baseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realm: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  adminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  opts: {
    adminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM),
    adminClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID),
  },
};

const ZAMMAD_FIELD_BY_ATTRIBUTE = {
  phoneNumber: "phone",
  street: "street",
  postal_code: "zip",
  locality: "city",
  country: "country",
};

function withDeadline(promise, ms, label) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} exceeded ${ms} ms`)), ms);
  });
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
}

exports.register = function (shared) {
  const baseUrl = shared.env.zammadBaseUrl;

  async function zammadApi() {
    const basic = Buffer.from(`${shared.env.adminApiUsername}:${shared.env.adminApiPassword}`).toString("base64");
    return request.newContext({
      ignoreHTTPSErrors: true,
      extraHTTPHeaders: { Authorization: `Basic ${basic}`, Accept: "application/json" },
    });
  }

  async function findUser(api, login) {
    const search = await apiGetOnion(api, `${baseUrl}/api/v1/users/search?query=${encodeURIComponent(login)}&limit=50`);
    expect(search.ok(), `GET /api/v1/users/search answered ${search.status()}`).toBe(true);
    const match = (await search.json()).find((user) => String(user.login).toLowerCase() === login.toLowerCase());
    if (!match) {
      return null;
    }
    const response = await apiGetOnion(api, `${baseUrl}/api/v1/users/${match.id}`);
    expect(response.ok(), `GET /api/v1/users/${match.id} answered ${response.status()}`).toBe(true);
    return response.json();
  }

  test("biber: an OIDC sign-in copies the phone_number and address claims onto the Zammad user", async ({ page, browser }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(240_000)); // one Keycloak attribute write and restore around one OIDC round-trip

    const suffix = String(Date.now()).slice(-6);
    const profile = {
      phoneNumber: `+4940${suffix}`,
      street: `Claimstrasse ${suffix}`,
      postal_code: suffix.slice(0, 5),
      locality: `Hamburg ${suffix}`,
      country: "DE",
    };
    const expected = Object.fromEntries(
      Object.entries(ZAMMAD_FIELD_BY_ATTRIBUTE).map(([attribute, field]) => [field, profile[attribute]]),
    );

    const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    const api = await zammadApi();
    let previous = null;
    let biberId = null;
    try {
      previous = await keycloakAdmin.keycloakAdminSetUserAttributes(
        adminCtx.request,
        keycloak.baseUrl,
        keycloak.realm,
        shared.env.biberUsername,
        profile,
        keycloak.adminUsername,
        keycloak.adminPassword,
        keycloak.opts,
      );

      await shared.signInViaZammadOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber");
      await expect(page.locator("body")).toContainText(/dashboard|ticket|overview|zammad/i, { timeout: resolveTimeout(60_000) });

      let account = null;
      await expect
        .poll(
          async () => {
            account = await findUser(api, shared.env.biberUsername);
            return account ? Object.fromEntries(Object.keys(expected).map((field) => [field, account[field]])) : null;
          },
          {
            timeout: resolveTimeout(60_000),
            message: "the OIDC sign-in must copy phone_number and address.street_address, postal_code, locality and country onto the Zammad user",
          },
        )
        .toEqual(expected);
      biberId = account.id;

      await shared.zammadLogout(page);
    } finally {
      const cleanup = async () => {
        if (previous) {
          await keycloakAdmin.keycloakAdminSetUserAttributes(
            adminCtx.request,
            keycloak.baseUrl,
            keycloak.realm,
            shared.env.biberUsername,
            previous,
            keycloak.adminUsername,
            keycloak.adminPassword,
            keycloak.opts,
          );
        }
        if (previous && biberId !== null) {
          const restored = Object.fromEntries(
            Object.entries(ZAMMAD_FIELD_BY_ATTRIBUTE).map(([attribute, field]) => [field, (previous[attribute] || [])[0] || ""]),
          );
          await apiFetchOnion(api, `${baseUrl}/api/v1/users/${biberId}`, { method: "PUT", data: restored });
        }
      };
      await withDeadline(cleanup(), resolveTimeout(60_000), "restoring biber in Keycloak and Zammad").catch((err) =>
        console.warn(`Cleanup of biber's Zammad profile failed: ${err}`),
      );
      await api.dispose().catch(() => {});
      await adminCtx.close().catch(() => {});
    }
  });
};
