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
const { resolveTimeout } = require("../../timeouts");

// SPOT for the role-side OIDC adapter readiness contract. A role whose
// `templates/javascript/oidc.js.j2` wraps its Login link in a JS click
// handler (e.g. `keycloak.login()` with PKCE) MUST set this flag on
// `window` after the click interceptor is wired, so persona helpers can
// click the link without racing the adapter.
const OIDC_LOGIN_READY_FLAG = "__oidcLoginReady";

const OIDC_TRIGGER_NAME = /sso|openid|single[\s-]?sign/i;

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

  await usernameField.waitFor({ state: "visible", timeout: resolveTimeout(60_000) });
  await usernameField.fill(username);
  await usernameField.press("Tab").catch(() => {});
  await passwordField.fill(password);
  await signInButton.click({ timeout: resolveTimeout(30_000) });
}

async function performKeycloakLogin(page, username, password, canonicalDomain) {
  await performKeycloakLoginForm(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `Expected redirect back to ${canonicalDomain} after Keycloak login`,
    })
    .toContain(canonicalDomain);
}

// Click a role's in-app Login link to start the OIDC chain. Waits for
// the role's adapter to signal readiness (OIDC_LOGIN_READY_FLAG) before
// clicking, so the click hits the JS-wrapped handler (which stores
// PKCE state) and not the raw `href` (which would skip PKCE and break
// the post-login token exchange on PKCE-enforced clients). The 15s
// fallback covers roles whose Login link is purely static. Returns the
// Page that reached `openid-connect/auth` — the opener, or the popup for
// roles that hand the IdP off via `window.open` — else null.
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
  for (let attempt = 0; attempt < 2; attempt += 1) {
    let oidcLink = page
      .locator(
        "a[href*='openid_connect' i], a[href*='openid-connect' i], a[href*='/auth/auth/' i], form[action*='openid' i] button, a[data-testid*='oidc' i], button[data-testid*='oidc' i]",
      )
      .first();
    if (attempt > 0) {
      oidcLink = oidcLink
        .or(page.getByRole("button", { name: OIDC_TRIGGER_NAME }))
        .or(page.getByRole("link", { name: OIDC_TRIGGER_NAME }))
        .first();
    }
    const oidcVisible = await oidcLink
      .waitFor({ state: "visible", timeout: resolveTimeout(5_000) })
      .then(() => true)
      .catch(() => false);

    let loginLink = oidcLink;
    if (!oidcVisible) {
      const strictVisible = await strictLink
        .waitFor({ state: "visible", timeout: resolveTimeout(20_000) })
        .then(() => true)
        .catch(() => false);
      loginLink = strictVisible ? strictLink : looseLink;
      if (!strictVisible) {
        const looseVisible = await loginLink
          .waitFor({ state: "visible", timeout: resolveTimeout(5_000) })
          .then(() => true)
          .catch(() => false);
        if (!looseVisible) return null;
      }
    }

    await page
      .waitForFunction(
        (flag) => window[flag] === true,
        OIDC_LOGIN_READY_FLAG,
        { timeout: resolveTimeout(15_000) },
      )
      .catch(() => {});
    const urlBeforeClick = page.url();
    const reachedIdp = (candidate) =>
      candidate
        .waitForURL(/openid-connect\/auth/, { timeout: resolveTimeout(15_000) })
        .then(() => candidate);
    const popupPromise = page
      .waitForEvent("popup", { timeout: resolveTimeout(15_000) })
      .then(reachedIdp);
    await loginLink.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
    const authPage = await Promise.any([reachedIdp(page), popupPromise]).catch(
      () => null,
    );
    if (authPage) return authPage;
    if (page.url().includes("openid-connect/auth")) return page;
    if (page.url() === urlBeforeClick) return null;
  }
  return null;
}

async function performKeycloakLoginExpectingDenial(page, username, password, canonicalDomain) {
  await performKeycloakLoginForm(page, username, password);

  await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(60_000) }).catch(() => {});

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
