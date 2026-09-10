/**
 * Logout via the role's own in-app logout control.
 *
 * MUST simulate the user clicking the role's logout button on the
 * currently rendered authenticated surface. Direct URL navigation to
 * any logout endpoint is FORBIDDEN.
 *
 * The universal-logout service (`web-svc-logout`), when attached to a
 * deployment, injects JavaScript that auto-detects every logout control
 * across the apps and rewrites it to redirect through Keycloak's
 * end-session endpoint. The persona helper therefore does NOT branch
 * on whether universal-logout is active: it just clicks the role's own
 * logout button. The injected JS handles the redirect when active, the
 * click clears the local session when not.
 *
 * Resolution order (each step a real click):
 *
 *   1. Click a logout control rendered on the current authenticated
 *      surface (link or button matching `logout` / `sign out` /
 *      `sign-out` / `abmelden`).
 *   2. If the logout control sits behind a user / account menu, open
 *      every plausible menu trigger and try again. Triggers include
 *      role=button / role=link elements whose accessible name contains
 *      `account` / `profile` / `user menu` / `menu`, plus
 *      framework-specific patterns (Bootstrap `data-bs-toggle="dropdown"`,
 *      `.dropdown-toggle`, ARIA `aria-haspopup="menu"`, etc.).
 *
 *   3. If neither surfaces one, follow a same-origin settings /
 *      preferences link and repeat steps 1 and 2 there.
 *
 * No further fallback. If none of the three surfaces a logout control,
 * the test fails — the role MUST expose an in-app logout somewhere a
 * user can click to.
 */

const { expect } = require("@playwright/test");
const { resolveTimeout } = require("../../timeouts");

const LOGOUT_NAME_RE = /log\s*out|sign\s*out|sign-out|abmelden/i;
const KEYCLOAK_LOGOUT_URL_RE = /\/protocol\/openid-connect\/logout/i;
const ACCOUNT_MENU_NAME_RE = /(account|\bprofile\b|user.?menu|^menu$|signed\s*in)/i;

async function clickFirstVisible(loc) {
  const count = await loc.count().catch(() => 0);
  for (let i = 0; i < count; i++) {
    const cand = loc.nth(i);
    if (await cand.isVisible().catch(() => false)) {
      await cand.click({ timeout: resolveTimeout(5_000) }).catch(() => {});
      return true;
    }
  }
  return false;
}

function logoutCandidatesOn(scope) {
  return [
    // The universal-logout JS injects a top-right fallback button when
    // the role's own surface has no logout control AND oauth2-proxy is
    // active. It marks the injected element with `data-injected-logout`
    // — check that first so oauth2-proxy-gated roles (Prometheus,
    // upstream-only UIs) have a guaranteed logout entry point.
    scope.locator("[data-injected-logout]"),
    scope.getByRole("menuitem", { name: LOGOUT_NAME_RE }),
    scope.getByRole("link", { name: LOGOUT_NAME_RE }),
    scope.getByRole("button", { name: LOGOUT_NAME_RE }),
    scope.locator(
      "a[href*='logout' i], a[href*='signout' i], a[href*='sign-out' i], a[href*='end_session' i], a[href*='end-session' i]",
    ),
    scope.locator("a:not([href])").filter({ hasText: LOGOUT_NAME_RE }),
  ];
}

async function tryLogoutFrom(scope) {
  for (const loc of logoutCandidatesOn(scope)) {
    if (await clickFirstVisible(loc)) return true;
  }
  return false;
}

function menuTriggerCandidatesOn(scope) {
  return [
    scope.getByRole("button", { name: ACCOUNT_MENU_NAME_RE }),
    scope.getByRole("link", { name: ACCOUNT_MENU_NAME_RE }),
    scope.locator(
      "[data-bs-toggle='dropdown'], .dropdown-toggle, [aria-haspopup='menu'], [aria-haspopup='true'], [data-region='user-menu-toggle'], .user-menu-toggle, .usermenu, [aria-label*='user menu' i], [aria-label*='account' i], [data-testid*='user' i]:not(input):not(textarea):not(select)",
    ),
  ];
}

const POLL_INTERVAL_MS = 250;

async function waitForLogoutControl(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const loc of logoutCandidatesOn(page)) {
      const count = await loc.count().catch(() => 0);
      for (let i = 0; i < count; i++) {
        if (await loc.nth(i).isVisible().catch(() => false)) return true;
      }
    }
    await page.waitForTimeout(POLL_INTERVAL_MS);
  }
  return false;
}

async function waitForAnyLogoutCandidate(page, timeoutMs = resolveTimeout(30_000), extraCandidates = []) {
  // Returns true on the first visible logout-shaped element, menu trigger
  // (Account/Profile) or extra candidate. Async-rendered post-login UIs
  // (e.g. dashboard's CDN-loaded keycloak-js + token exchange) routinely
  // exceed 10s before the Account dropdown is even visible; bumped from
  // 10s to 30s.
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const loc of [...logoutCandidatesOn(page), ...menuTriggerCandidatesOn(page), ...extraCandidates]) {
      const count = await loc.count().catch(() => 0);
      for (let i = 0; i < count; i++) {
        const cand = loc.nth(i);
        if (await cand.isVisible().catch(() => false)) {
          return true;
        }
      }
    }
    await page.waitForTimeout(POLL_INTERVAL_MS);
  }
  return false;
}

async function tryLogoutViaMenus(page) {
  // Try every visible trigger — the first match is not necessarily the
  // one wrapping the logout entry (Bootstrap navbars often render
  // multiple dropdown toggles).
  const tried = new Set();
  for (const triggerLoc of menuTriggerCandidatesOn(page)) {
    const count = await triggerLoc.count().catch(() => 0);
    for (let i = 0; i < count; i++) {
      const trigger = triggerLoc.nth(i);
      if (!(await trigger.isVisible().catch(() => false))) continue;
      const key = await trigger.evaluate((el) => el.outerHTML.slice(0, 200)).catch(() => "");
      if (key && tried.has(key)) continue;
      tried.add(key);
      await trigger.click({ timeout: resolveTimeout(5_000) }).catch(() => {});
      // Give the dropdown / popover time to render its items.
      await waitForLogoutControl(page, resolveTimeout(1_500));
      if (await tryLogoutFrom(page)) {
        await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        return true;
      }
      // Close again before trying the next trigger so overlay menus do
      // not stack and hide each other.
      await trigger.click({ timeout: resolveTimeout(2_000) }).catch(() => {});
    }
  }
  return false;
}

function settingsLinksOn(scope) {
  return scope.locator(
    "a[href^='/'][href*='setting' i], a[href^='/'][href*='preference' i], a[href^='/'][href*='einstellung' i]",
  );
}

async function openAccountSettings(page) {
  const links = settingsLinksOn(page);
  const count = await links.count().catch(() => 0);
  for (let i = 0; i < count; i++) {
    const link = links.nth(i);
    if (!(await link.isVisible().catch(() => false))) continue;
    await link.click({ timeout: resolveTimeout(5_000) }).catch(() => {});
    await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
    return true;
  }
  return false;
}

/**
 * Keycloak renders a "Do you want to log out?" confirmation page when the
 * end-session request carries no id_token_hint (the injected universal-logout
 * control cannot know the id_token). A real user clicks the confirm button;
 * without it the Keycloak SSO session — and every app session — survives.
 */
async function confirmKeycloakLogoutIfPrompted(page) {
  if (!KEYCLOAK_LOGOUT_URL_RE.test(page.url())) return;
  const confirmBtn = page
    .locator("#kc-logout, form[action*='logout-confirm'] input[type='submit'], form[action*='logout-confirm'] button")
    .first();
  const prompted = await Promise.race([
    confirmBtn.waitFor({ state: "visible", timeout: resolveTimeout(2_000) }).then(() => true),
    page
      .waitForURL((url) => !KEYCLOAK_LOGOUT_URL_RE.test(url.href), {
        waitUntil: "commit",
        timeout: resolveTimeout(2_000),
      })
      .then(() => false),
  ]).catch(() => false);
  if (prompted) {
    await confirmBtn.click({ timeout: resolveTimeout(10_000) }).catch(() => {});
    await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
  }
}

async function inAppLogout(page) {
  await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});

  await waitForLogoutControl(page, resolveTimeout(3_000));
  await waitForAnyLogoutCandidate(page, resolveTimeout(30_000), [settingsLinksOn(page)]);

  if (await tryLogoutFrom(page)) {
    await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
    await confirmKeycloakLogoutIfPrompted(page);
    return;
  }

  if (await tryLogoutViaMenus(page)) {
    await confirmKeycloakLogoutIfPrompted(page);
    return;
  }

  if (await openAccountSettings(page)) {
    await waitForAnyLogoutCandidate(page, resolveTimeout(5_000));
    if (await tryLogoutFrom(page)) {
      await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
      await confirmKeycloakLogoutIfPrompted(page);
      return;
    }
    if (await tryLogoutViaMenus(page)) {
      await confirmKeycloakLogoutIfPrompted(page);
      return;
    }
  }

  const _loginSurfaceVisible = await page
    .locator("input[type='password']")
    .first()
    .isVisible()
    .catch(() => false);
  if (_loginSurfaceVisible) {
    expect
      .soft(false, "session was lost before the logout attempt - a login surface is visible instead of the authenticated app")
      .toBe(true);
    return;
  }
  const _bodyText = await page
    .locator("body")
    .innerText()
    .catch(() => "");
  if (_bodyText.trim().length === 0) {
    expect
      .soft(false, "session was lost before the logout attempt - the page rendered an empty unauthenticated shell")
      .toBe(true);
    return;
  }
  expect.soft(false, "no in-app logout control reachable on the current authenticated surface").toBe(true);
}

module.exports = { inAppLogout, confirmKeycloakLogoutIfPrompted, waitForLogoutControl };
