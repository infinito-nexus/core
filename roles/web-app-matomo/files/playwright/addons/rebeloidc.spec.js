const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { expectNoCspViolations, gotoOnion, performKeycloakLogin } = require("../personas");
const {
  appBaseUrl,
  canonicalDomain,
  rbacAdminUsername,
  rbacAdminPassword,
  matomoOidcPlugin,
  attachDiagnostics,
  setupMatomoPage,
  expectLoginForm,
  startOidcLogin,
  matomoApi,
  nativeLoginEnabled,
  LOGIN_FIELD,
  oidcButtonSelector,
} = require("../_shared");

const ADMIN_MENU = "#secondNavBar.Menu--admin";
const LOGOUT_LINK = "a[href*='module=Login'][href*='action=logout']";
const KEYCLOAK_LOGOUT_CONFIRM = "#kc-logout";
const KEYCLOAK_USERNAME = "input#username, input[name='username']";

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async ({ page }) => {
  await setupMatomoPage(page);
});

test("addon rebeloidc: the Matomo login sends its Keycloak button to the authorization endpoint with the client and a callback on the same origin", async ({ page }) => {
  skipUnlessAddonEnabled("rebeloidc");
  skipUnlessServiceEnabled("sso");

  await startOidcLogin(page);

  const authUrl = new URL(page.url());
  expect(authUrl.searchParams.get("client_id") || "", "the authorization request MUST carry the OAuth client").not.toBe("");
  expect(
    (authUrl.searchParams.get("scope") || "").split(" "),
    "the authorization request MUST ask for the openid, profile and email scopes",
  ).toEqual(expect.arrayContaining(["openid", "profile", "email"]));

  const callback = new URL(authUrl.searchParams.get("redirect_uri") || "about:blank");
  expect(
    callback.origin,
    "the callback MUST return to the scheme and host the login started on, which needs Matomo to read X-Forwarded-Proto",
  ).toBe(new URL(appBaseUrl).origin);
  expect(callback.searchParams.get("module"), "the callback MUST hit the OIDC plugin").toBe(matomoOidcPlugin);
  expect(callback.searchParams.get("action"), "the callback MUST hit the plugin's callback action").toBe("callback");
});

test("administrator: the RBAC administrator signs in through Keycloak as Matomo superuser and the sign-out ends the Keycloak session", async ({ page }) => {
  skipUnlessAddonEnabled("rebeloidc");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));
  expect(rbacAdminUsername, "RBAC_ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(rbacAdminPassword, "RBAC_ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();

  const diagnostics = attachDiagnostics(page);
  await startOidcLogin(page);
  await performKeycloakLogin(page, rbacAdminUsername, rbacAdminPassword, canonicalDomain);

  const account = await matomoApi(page.request, "UsersManager.getUser", { userLogin: rbacAdminUsername });
  expect(
    [1, "1", true],
    `the deploy MUST have granted ${rbacAdminUsername}, a member of the administrator role, Matomo superuser access (got ${JSON.stringify(account)})`,
  ).toContain(account?.superuser_access);

  await gotoOnion(
    page,
    `${appBaseUrl}/index.php?module=CoreAdminHome&action=generalSettings&idSite=1&period=day&date=yesterday`,
  );
  await expect(
    page.locator(ADMIN_MENU),
    "the superuser-only General settings entry MUST be in the administration menu of the OIDC session",
  ).toContainText(/General settings/i, { timeout: resolveTimeout(60_000) });
  await expect(page.locator("body")).not.toContainText(/could only detect a non secure connection/i);
  await expectNoCspViolations(page, diagnostics, "matomo oidc administrator");

  await page.locator(LOGOUT_LINK).first().click();
  const confirm = page.locator(KEYCLOAK_LOGOUT_CONFIRM);
  const loginEntry = page.locator(nativeLoginEnabled ? LOGIN_FIELD : oidcButtonSelector());
  await expect(confirm.or(loginEntry).first()).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  if (await confirm.isVisible()) {
    await confirm.click();
  }
  await expectLoginForm(page, "the sign-out MUST end on the Matomo login form");

  await startOidcLogin(page);
  await expect(
    page.locator(KEYCLOAK_USERNAME).first(),
    "the sign-out MUST have ended the Keycloak session, so a new OIDC login asks for credentials again",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
});
