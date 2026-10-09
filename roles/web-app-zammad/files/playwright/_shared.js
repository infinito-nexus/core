const { expect, request } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm, runGuestFlow } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");

const oidcEnabled    = isServiceEnabled("sso");
const oidcIssuerUrl  = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const zammadBaseUrl  = normalizeBaseUrl(process.env.ZAMMAD_BASE_URL || "");
const adminUsername    = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminEmail       = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL);
const adminPassword    = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const adminApiUsername = decodeDotenvQuotedValue(process.env.ADMIN_API_USERNAME);
const adminApiPassword = decodeDotenvQuotedValue(process.env.ADMIN_API_PASSWORD);
const biberUsername  = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword  = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

async function zammadLogout(page) {
  await gotoOnion(page, `${zammadBaseUrl}/#logout`, { waitUntil: "commit" }).catch(() => {});
  if (oidcIssuerUrl) {
    await gotoOnion(page, `${oidcIssuerUrl}/protocol/openid-connect/logout`, { waitUntil: "commit" }).catch(() => {});
  }
  await page.context().clearCookies();
}

/**
 * Seed a ticket over the Basic-auth REST API.
 *
 * @param {string} subject ticket title and article subject.
 * @param {string} body article body.
 * @returns {Promise<object>} the ticket as Zammad returned it.
 */
async function seedTicketViaApi(subject, body) {
  const api = await request.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: {
      Authorization: `Basic ${Buffer.from(`${adminApiUsername}:${adminApiPassword}`).toString("base64")}`,
      "Content-Type": "application/json",
    },
  });

  const resp = await api.post(`${zammadBaseUrl}/api/v1/tickets`, {
    data: {
      title: subject,
      group: "Users",
      customer: adminApiUsername,
      article: {
        subject,
        body,
        type: "note",
        internal: false,
      },
    },
  });

  if (resp.status() >= 300) {
    throw new Error(`Seed POST /api/v1/tickets failed: ${resp.status()} ${await resp.text()}`);
  }
  const ticket = await resp.json();
  await api.dispose();
  return ticket;
}

async function signInAsApiBot(page) {
  // page.context().request shares the browser cookie jar; in-page fetch hits Keycloak cross-origin in OIDC variants.
  await page.context().clearCookies();

  const apiRequest = page.context().request;

  const seed = await apiRequest.get(`${zammadBaseUrl}/api/v1/signshow`, {
    headers: { Accept: "application/json" },
    failOnStatusCode: true,
  });
  const csrfToken = seed.headers()["csrf-token"];
  if (!csrfToken) {
    throw new Error("could not lift the csrf token from signshow");
  }

  const signin = await apiRequest.post(`${zammadBaseUrl}/api/v1/signin`, {
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-CSRF-Token": csrfToken,
    },
    data: { username: adminApiUsername, password: adminApiPassword, fingerprint: "playwright" },
  });
  if (!signin.ok()) {
    throw new Error(`signin failed: ${signin.status()} ${await signin.text()}`);
  }

  await gotoOnion(page, `${zammadBaseUrl}/`, { waitUntil: "domcontentloaded" });
}

async function signInViaZammadOidc(page, username, password, personaLabel) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await gotoOnion(page, `${zammadBaseUrl}/`);

  const oidcSignIn = page
    .locator("a, button")
    .filter({ hasText: /openid|sign\s*in\s+with|continue\s+with|single\s+sign[-\s]*on|infinito/i })
    .first();

  if ((await oidcSignIn.count().catch(() => 0)) > 0) {
    await oidcSignIn.click({ timeout: resolveTimeout(30_000) });
  } else {
    await gotoOnion(page, `${zammadBaseUrl}/auth/openid_connect`).catch(() => {});
  }

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `${personaLabel}: expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `${personaLabel}: expected redirect back to Zammad at ${zammadBaseUrl}`
    })
    .toContain(canonicalDomain);
}

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });

  expect(zammadBaseUrl,   "ZAMMAD_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
}

module.exports = {
  env: {
    oidcEnabled,
    oidcIssuerUrl,
    zammadBaseUrl,
    adminUsername,
    adminEmail,
    adminPassword,
    adminApiUsername,
    adminApiPassword,
    biberUsername,
    biberPassword,
    canonicalDomain,
  },
  seedTicketViaApi,
  signInViaZammadOidc,
  signInAsApiBot,
  zammadLogout,
  beforeEach,
  skipUnlessServiceEnabled,
  runGuestFlow,
};
