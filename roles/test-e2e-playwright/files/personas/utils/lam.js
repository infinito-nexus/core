const { expect } = require("@playwright/test");
const { resolveTimeout } = require("../../timeouts");
const { performKeycloakLoginForm } = require("./keycloak");
const { gotoOnion } = require("./onion");

const LAM_SSO_HOP = /\/protocol\/openid-connect\/|\/login-actions\/|\/oauth2\//;
const LAM_LOGIN_USERNAME = "input#username";
const LAM_LOGIN_PASSWORD = "input#passwd";
const LAM_LOGIN_BUTTON = 'button[name="checklogin"]';
const LAM_SIGNED_IN = '#lam-topnav a.lam-menu-entry[href$="/templates/lists/list.php?type=user"]';

/**
 * Args:
 *   page: browser page without a LAM session.
 *   lamBaseUrl: base URL of LAM.
 *   username: user name LAM's search login looks up under the users OU; also the Keycloak login of the oauth2-proxy gate.
 *   password: LDAP password of that account; also its Keycloak password.
 */
async function signInToLam(page, lamBaseUrl, username, password) {
  const loginUrl = `${lamBaseUrl.replace(/\/+$/, "")}/lam/templates/login.php`;
  await gotoOnion(page, loginUrl, { waitUntil: "load" });
  if (LAM_SSO_HOP.test(page.url())) {
    await performKeycloakLoginForm(page, username, password);
    await page.waitForURL((url) => !LAM_SSO_HOP.test(String(url)), {
      timeout: resolveTimeout(60_000),
      waitUntil: "domcontentloaded",
    });
    await gotoOnion(page, loginUrl, { waitUntil: "load" });
  }
  const user = page.locator(LAM_LOGIN_USERNAME);
  const secret = page.locator(LAM_LOGIN_PASSWORD);
  await expect(user, "LAM must render the user name field of its search login").toBeEditable({
    timeout: resolveTimeout(30_000),
  });
  await user.fill(username);
  await expect(secret, "LAM must render the password field of its search login").toBeEditable({
    timeout: resolveTimeout(30_000),
  });
  await secret.fill(password);
  await page.locator(LAM_LOGIN_BUTTON).click({ timeout: resolveTimeout(30_000) });
  await page.waitForLoadState("domcontentloaded");
  await expect(
    page.locator(LAM_SIGNED_IN),
    `${username} must reach LAM's account list through the search login`,
  ).toHaveCount(1, { timeout: resolveTimeout(30_000) });
}

module.exports = {
  signInToLam,
};
