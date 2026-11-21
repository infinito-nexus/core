const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { clickOidcLoginLink, gotoOnion, performKeycloakLogin } = require("./personas");

/**
 * Args:
 *   page: Playwright page without a wiki session; ends signed in through Keycloak.
 *   base: MediaWiki base URL without a trailing slash.
 *   canonicalDomain: canonical domain of the wiki, which the Keycloak login returns to.
 *   username: Keycloak username.
 *   password: Keycloak password.
 */
async function signInViaOidc(page, base, canonicalDomain, username, password) {
  await gotoOnion(page, `${base}/index.php?title=Special:UserLogin`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: resolveTimeout(30_000) }).catch(() => {});
  let authPage = page;
  if (!page.url().includes("openid-connect/auth")) {
    const strictLogin = page
      .getByRole("link", { name: /^\s*(log\s*in|sign\s*in|sso)\s*$/i })
      .or(page.getByRole("button", { name: /^\s*(log\s*in|sign\s*in|sso)\s*$/i }))
      .first();
    const looseLogin = page
      .getByRole("link", { name: /log\s*in|sign\s*in|sso/i })
      .or(page.getByRole("button", { name: /log\s*in|sign\s*in|sso/i }))
      .first();
    authPage = (await clickOidcLoginLink(page, strictLogin, looseLogin)) || page;
  }
  expect(
    authPage.url(),
    "Special:UserLogin MUST hand off to the Keycloak authorize endpoint",
  ).toContain("openid-connect/auth");
  await performKeycloakLogin(authPage, username, password, canonicalDomain);
}

module.exports = { signInViaOidc };
