/**
 * Keycloak OIDC login helpers.
 *
 *   `performKeycloakLoginForm(target, username, password)`
 *     Fills the Keycloak login form on `target` (a `Page` OR a
 *     `FrameLocator`) and clicks sign-in. Tolerates both the
 *     role-based selector strategy (`getByRole({ name: /username|
 *     email/i })`, etc.) and the legacy input-name selector strategy
 *     (`input[name='username']`, etc.) so iframe-embedded Keycloak
 *     forms work without branching at the call site. Does NOT assert
 *     post-login navigation.
 *
 *   `performKeycloakLogin(page, username, password, canonicalDomain)`
 *     Calls `performKeycloakLoginForm` and additionally polls the
 *     page URL until it contains `canonicalDomain`, asserting the
 *     OAuth2-Proxy / app callback completes.
 *
 *   `performKeycloakLoginExpectingDenial(page, username, password, canonicalDomain)`
 *     Drives the form with credentials expected to be REJECTED
 *     (insufficient privileges, forbidden role, denied app) and
 *     asserts the round-trip ends on a denial state (Keycloak error
 *     page, the same authorization endpoint with an error indicator,
 *     or a 401 / 403 on the relying party after the callback).
 *     Returns the resulting URL so callers can assert additional
 *     details if needed.
 */

const { expect } = require("@playwright/test");

// SPOT for the role-side OIDC adapter readiness contract. A role whose
// `templates/javascript/oidc.js.j2` wraps its Login link in a JS click
// handler (e.g. `keycloak.login()` with PKCE) MUST set this flag on
// `window` after the click interceptor is wired, so persona helpers can
// click the link without racing the adapter.
const OIDC_LOGIN_READY_FLAG = "__oidcLoginReady";

async function performKeycloakLoginForm(target, username, password) {
  const usernameField = target
    .getByRole("textbox", { name: /username|email/i })
    .or(target.locator("input[name='username'], input#username"))
    .first();
  const passwordField = target
    .getByRole("textbox", { name: /^password$/i })
    .or(target.locator("input[name='password'], input#password"))
    .first();
  const signInButton = target
    .getByRole("button", { name: /sign in|login|log in/i })
    .or(target.locator("input#kc-login, button#kc-login, button[type='submit'], input[type='submit']"))
    .first();

  await usernameField.waitFor({ state: "visible", timeout: 60_000 });
  await usernameField.fill(username);
  await usernameField.press("Tab").catch(() => {});
  await passwordField.fill(password);
  await signInButton.click();
}

async function performKeycloakLogin(page, username, password, canonicalDomain) {
  await performKeycloakLoginForm(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `Expected redirect back to ${canonicalDomain} after Keycloak login`,
    })
    .toContain(canonicalDomain);
}

// Click a role's in-app Login link to start the OIDC chain. Waits for
// the role's adapter to signal readiness (OIDC_LOGIN_READY_FLAG) before
// clicking, so the click hits the JS-wrapped handler (which stores
// PKCE state) and not the raw `href` (which would skip PKCE and break
// the post-login token exchange on PKCE-enforced clients). The 15s
// fallback covers roles whose Login link is purely static. Returns
// true when the navigation reached `openid-connect/auth`.
//
// The persona MUST pass `strictLink` (exact-match locator, e.g. accessible
// name `^\s*login\s*$/i`) AND `looseLink` (substring locator). The helper
// prefers the strict match — that targets the role's OWN Login button
// (e.g. nextcloud's plain `<a>Login</a>`) — and only falls back to the
// loose match when no strict candidate is visible. Without this two-pass
// approach, `sys-front-inj-all`-injected dashboard navbars in oauth2-proxy
// roles trap the substring match and redirect the persona to the dashboard
// flow instead of the role's own auth chain.
async function clickOidcLoginLink(page, strictLink, looseLink) {
  const strictVisible = await strictLink
    .waitFor({ state: "visible", timeout: 20_000 })
    .then(() => true)
    .catch(() => false);
  const loginLink = strictVisible ? strictLink : looseLink;
  if (!strictVisible) {
    const looseVisible = await loginLink
      .waitFor({ state: "visible", timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    if (!looseVisible) return false;
  }

  await page
    .waitForFunction(
      (flag) => window[flag] === true,
      OIDC_LOGIN_READY_FLAG,
      { timeout: 15_000 },
    )
    .catch(() => {});
  await loginLink.click().catch(() => {});
  await page
    .waitForURL(/openid-connect\/auth/, { timeout: 15_000 })
    .catch(() => {});
  return page.url().includes("openid-connect/auth");
}

async function performKeycloakLoginExpectingDenial(page, username, password, canonicalDomain) {
  await performKeycloakLoginForm(page, username, password);

  await page.waitForLoadState("domcontentloaded", { timeout: 60_000 }).catch(() => {});

  const finalUrl = page.url();
  const denied =
    /access[\s_-]?denied|forbidden|not[\s_-]?authori[sz]ed|unauthori[sz]ed/i.test(
      await page.content().catch(() => ""),
    ) ||
    /openid-connect\/auth/.test(finalUrl) ||
    !finalUrl.includes(canonicalDomain);

  expect(
    denied,
    `Expected ${username} to be DENIED at ${canonicalDomain} after Keycloak login (got URL ${finalUrl})`,
  ).toBe(true);

  return finalUrl;
}

module.exports = {
  OIDC_LOGIN_READY_FLAG,
  performKeycloakLoginForm,
  performKeycloakLogin,
  clickOidcLoginLink,
  performKeycloakLoginExpectingDenial,
};
