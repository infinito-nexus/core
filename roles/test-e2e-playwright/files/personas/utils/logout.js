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
 * No further fallback. If no trigger surfaces a logout control, the
 * test fails — the role's authenticated surface MUST expose an in-app
 * logout.
 */

const { expect } = require("@playwright/test");

const LOGOUT_NAME_RE = /log\s*out|sign\s*out|sign-out|abmelden/i;
const ACCOUNT_MENU_NAME_RE = /(account|profile|user.?menu|^menu$|sign\s*in|signed\s*in)/i;

async function clickFirstVisible(loc, { timeout = 5_000 } = {}) {
  const count = await loc.count().catch(() => 0);
  for (let i = 0; i < count; i++) {
    const cand = loc.nth(i);
    if (await cand.isVisible({ timeout }).catch(() => false)) {
      await cand.click({ timeout: 5_000 }).catch(() => {});
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
      "[data-bs-toggle='dropdown'], .dropdown-toggle, [aria-haspopup='menu'], [aria-haspopup='true'], [data-region='user-menu-toggle'], .user-menu-toggle, .usermenu, [aria-label*='user menu' i], [aria-label*='account' i], [data-testid*='user' i]",
    ),
  ];
}

async function waitForAnyLogoutCandidate(page, timeoutMs = 30_000) {
  // Returns true on the first visible logout-shaped element OR menu trigger
  // (Account/Profile). Async-rendered post-login UIs (e.g. dashboard's
  // CDN-loaded keycloak-js + token exchange) routinely exceed 10s before
  // the Account dropdown is even visible — bumped from 10s to 30s.
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const loc of [...logoutCandidatesOn(page), ...menuTriggerCandidatesOn(page)]) {
      const count = await loc.count().catch(() => 0);
      for (let i = 0; i < count; i++) {
        const cand = loc.nth(i);
        if (await cand.isVisible({ timeout: 500 }).catch(() => false)) {
          return true;
        }
      }
    }
    await page.waitForTimeout(250);
  }
  return false;
}

async function inAppLogout(page) {
  await page.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});

  await waitForAnyLogoutCandidate(page);

  if (await tryLogoutFrom(page)) {
    await page.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
    return;
  }

  const menuTriggers = menuTriggerCandidatesOn(page);

  // Try every visible trigger — the first match is not necessarily the
  // one wrapping the logout entry (Bootstrap navbars often render
  // multiple dropdown toggles).
  const tried = new Set();
  for (const triggerLoc of menuTriggers) {
    const count = await triggerLoc.count().catch(() => 0);
    for (let i = 0; i < count; i++) {
      const trigger = triggerLoc.nth(i);
      if (!(await trigger.isVisible({ timeout: 1_000 }).catch(() => false))) continue;
      const key = await trigger.evaluate((el) => el.outerHTML.slice(0, 200)).catch(() => "");
      if (key && tried.has(key)) continue;
      tried.add(key);
      await trigger.click({ timeout: 5_000 }).catch(() => {});
      // Give the dropdown / popover time to render its items.
      await page.waitForTimeout(750);
      if (await tryLogoutFrom(page)) {
        await page.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        return;
      }
      // Close again before trying the next trigger so overlay menus do
      // not stack and hide each other.
      await trigger.click({ timeout: 2_000 }).catch(() => {});
    }
  }

  expect.soft(false, "no in-app logout control reachable on the current authenticated surface").toBe(true);
}

module.exports = { inAppLogout };
