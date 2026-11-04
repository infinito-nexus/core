const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const {
  apiFetchOnion,
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");

const oidcIssuerUrl     = normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));
const jellyfinBaseUrl   = normalizeBaseUrl(process.env.JELLYFIN_BASE_URL || "");
const adminUsername     = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminNativePassword = decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD);
const biberUsername     = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword     = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain   = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);
const adminGroupPath    = decodeDotenvQuotedValue(process.env.JELLYFIN_ADMIN_GROUP_PATH);
const keycloakBaseUrl   = normalizeBaseUrl(requireDotenvValue(process.env.KEYCLOAK_BASE_URL, "KEYCLOAK_BASE_URL"));
const keycloakRealm     = decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME);
const keycloakAdminUsername = decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_USERNAME);
const keycloakAdminPassword = decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_PASSWORD);
const ldapAdminUsername = decodeDotenvQuotedValue(process.env.LDAP_ADMIN_USERNAME);
const ldapAdminPassword = decodeDotenvQuotedValue(process.env.LDAP_ADMIN_PASSWORD);
const loginMethodSso    = process.env.LOGIN_METHOD_SSO_ENABLED === "true";
const loginMethodLdap   = process.env.LOGIN_METHOD_LDAP_ENABLED === "true";
const loginMethodNative = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const loginFormShown    = loginMethodLdap || loginMethodNative;

const BREAK_GLASS_CLIENT = 'MediaBrowser Client="playwright", Device="break-glass", DeviceId="infinito-break-glass", Version="1.0.0"';

async function gotoLogin(page) {
  await gotoOnion(page, `${jellyfinBaseUrl}/web/`, { waitUntil: "domcontentloaded" });
}

function onLoginSurface(page) {
  return /\/web\/(?:index\.html)?#\/login(?:\.html)?(?:[?/]|$)/.test(page.url());
}

async function assertAuthenticated(page, label) {
  await expect(
    page
      .getByRole("button", { name: "Menu" })
      .or(page.getByRole("button", { name: "Search" }))
      .first(),
    `${label}: authenticated Jellyfin chrome must be visible`,
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function fillManualLogin(page, username, password) {
  const userField = page.locator("#txtManualName, input[name='username'], input[type='text']").first();
  await userField.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await userField.fill(username);
  const passwordField = page.locator("#txtManualPassword, input[type='password']").first();
  await expect(passwordField).toBeEditable({ timeout: resolveTimeout(30_000) });
  await passwordField.fill(password);
  await page
    .locator("button[type='submit'], .btnSubmit")
    .first()
    .click({ timeout: resolveTimeout(30_000) })
    .catch(() => page.keyboard.press("Enter"));
}

async function signInViaLocal(page, username, password, label) {
  await gotoLogin(page);
  await fillManualLogin(page, username, password);
  await assertAuthenticated(page, label);
}

async function signInViaLdap(page, username, password, label) {
  await signInViaLocal(page, username, password, label);
}

/**
 * Args:
 *   page: Playwright page the API session of the local account is handed to.
 *   username: local Jellyfin account, normally the break-glass administrator.
 *   password: its local password.
 *   label: assertion label.
 */
async function signInViaBreakGlass(page, username, password, label) {
  const response = await apiFetchOnion(page.request, `${jellyfinBaseUrl}/Users/AuthenticateByName`, {
    method: "POST",
    headers: { "X-Emby-Authorization": BREAK_GLASS_CLIENT },
    data: { Username: username, Pw: password },
  });
  expect(response.status(), `${label}: POST /Users/AuthenticateByName must sign the local account in`).toBe(200);
  const session = await response.json();
  await gotoLogin(page);
  await expect
    .poll(
      () => page.evaluate(() => (JSON.parse(window.localStorage.getItem("jellyfin_credentials") || "{}").Servers || []).length),
      {
        timeout: resolveTimeout(30_000),
        message: `${label}: the Jellyfin web client must register its server before it takes over an API session`,
      },
    )
    .toBeGreaterThan(0);
  await page.evaluate(
    ({ serverId, accessToken, userId }) => {
      const credentials = JSON.parse(window.localStorage.getItem("jellyfin_credentials"));
      for (const server of credentials.Servers) {
        server.Id = serverId;
        server.AccessToken = accessToken;
        server.UserId = userId;
      }
      window.localStorage.setItem("jellyfin_credentials", JSON.stringify(credentials));
    },
    { serverId: session.ServerId, accessToken: session.AccessToken, userId: session.User.Id },
  );
  await gotoOnion(page, `${jellyfinBaseUrl}/web/#/home`, { waitUntil: "domcontentloaded" });
  await assertAuthenticated(page, label);
}

/**
 * Args:
 *   page: Playwright page that signs the local administrator in.
 *   label: assertion label.
 */
async function signInAsLocalAdministrator(page, label) {
  const signIn = loginFormShown ? signInViaLocal : signInViaBreakGlass;
  await signIn(page, adminUsername, adminNativePassword, label);
}

async function signInViaOidc(page, username, password, label) {
  await gotoLogin(page);
  const oidcButton = page
    .locator("a, button")
    .filter({ hasText: /sign\s*in\s*with|keycloak|single\s*sign|sso|openid/i })
    .first();
  await expect(
    oidcButton,
    `${label}: the SSO provider button must render on the Jellyfin login page`,
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
  await oidcButton.click({ timeout: resolveTimeout(30_000) });

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `${label}: expected redirect to Keycloak (${oidcIssuerUrl}/protocol/openid-connect/auth)`,
    })
    .toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);

  await performKeycloakLoginForm(page, username, password);
  await assertAuthenticated(page, label);
}

async function sessionUser(page, label) {
  const credentials = await page.evaluate(() => window.localStorage.getItem("jellyfin_credentials"));
  expect(credentials, `${label}: the Jellyfin web client must store its credentials after sign-in`).toBeTruthy();
  const token = JSON.parse(credentials).Servers.map((server) => server.AccessToken).find(Boolean);
  expect(token, `${label}: the stored Jellyfin credentials must carry an access token`).toBeTruthy();
  const response = await apiFetchOnion(page.request, `${jellyfinBaseUrl}/Users/Me`, {
    method: "GET",
    headers: { "X-Emby-Token": token },
  });
  expect(response.status(), `${label}: GET /Users/Me must answer for the signed-in user`).toBe(200);
  return response.json();
}

async function sessionIsAdministrator(page, label) {
  const user = await sessionUser(page, label);
  return user.Policy.IsAdministrator === true;
}

async function logout(page, label = "session") {
  try {
    const menu = page
      .getByRole("button", { name: "Menu" })
      .or(page.locator(".headerUserButton, .mainDrawerButton"))
      .first();
    if (await menu.count()) {
      await menu.click({ timeout: resolveTimeout(5_000) }).catch(() => {});
    }
    const signOut = page
      .getByRole("link", { name: /sign\s*out|log\s*out|logout|abmelden/i })
      .or(page.locator("a, button, .listItem").filter({ hasText: /sign\s*out|log\s*out|logout|abmelden/i }))
      .first();
    if (await signOut.count()) {
      await signOut.click({ timeout: resolveTimeout(5_000) }).catch(() => {});
      await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(8_000) }).catch(() => {});
    }
  } catch {
    /* best-effort */
  }

  await page.context().clearCookies();
  await gotoLogin(page).catch(() => {});
  await page
    .evaluate(() => {
      try {
        window.localStorage.clear();
        window.sessionStorage.clear();
      } catch {
        /* noop */
      }
    })
    .catch(() => {});
  await gotoLogin(page);
  await expect
    .poll(() => onLoginSurface(page), {
      timeout: resolveTimeout(30_000),
      message: `${label}: expected logged-out landing on the Jellyfin login surface`,
    })
    .toBe(true);
}

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(jellyfinBaseUrl, "JELLYFIN_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
}

module.exports = {
  env: {
    oidcIssuerUrl,
    jellyfinBaseUrl,
    adminUsername,
    adminNativePassword,
    biberUsername,
    biberPassword,
    canonicalDomain,
    adminGroupPath,
    keycloakBaseUrl,
    keycloakRealm,
    keycloakAdminUsername,
    keycloakAdminPassword,
    ldapAdminUsername,
    ldapAdminPassword,
    loginMethodSso,
    loginMethodLdap,
    loginMethodNative,
    loginFormShown,
  },
  gotoLogin,
  onLoginSurface,
  assertAuthenticated,
  signInViaLocal,
  signInViaLdap,
  signInViaOidc,
  signInViaBreakGlass,
  signInAsLocalAdministrator,
  sessionUser,
  sessionIsAdministrator,
  logout,
  beforeEach,
  skipUnlessServiceDisabled,
  skipUnlessServiceEnabled,
};
