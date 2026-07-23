/**
 * `biber` persona: single-app authenticated journey.
 *
 *   appBaseUrl → (OIDC if applicable) → CSP injection check
 *              → role-specific interaction → in-app logout
 *              → unauthenticated landing assertion.
 *
 * Cross-service surface checks (prometheus deny, matomo deny,
 * dashboard tile reachability) are owned by the dedicated provider
 * specs and no longer run as part of every role's biber persona:
 *
 *   - `roles/web-app-prometheus/files/playwright/playwright.spec.js` parameterises
 *     scrape-target presence + admin reach + biber denial.
 *   - `roles/web-app-matomo/files/playwright/playwright.spec.js` parameterises
 *     tracker-site presence + admin reach + biber denial.
 *   - `roles/web-app-dashboard/files/playwright/playwright.spec.js` parameterises
 *     dashboard-tile reachability per consumer role.
 *
 * Each role's biber scenario therefore visits its OWN canonical URL
 * directly (no dashboard tile click) and exercises only that role.
 */

const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const {
  normalizeUrl,
  readEnv,
  safeIsEnabled,
  gotoOnion,
  performKeycloakLogin,
  clickOidcLoginLink,
  inAppLogout,
  assertUnauthenticatedLanding,
  assertCspInjections,
  runRoleInteraction,
} = require("./utils");

async function runBiberFlow(page, opts = {}) {
  if ((process.env.PERSONA_BIBER_BLOCKED || "").toLowerCase() === "true") {
    test.skip(
      true,
      `biber persona is explicitly blocked by the role contract (PERSONA_BIBER_BLOCKED=true). See the role's TODO.md for the rationale and the path back to a runnable journey.`,
    );
    return;
  }

  safeIsEnabled("sso");
  safeIsEnabled("logout");
  safeIsEnabled("matomo");

  const canonicalDomain = readEnv("CANONICAL_DOMAIN");
  const appBaseUrl = normalizeUrl(process.env.APP_BASE_URL);
  const biberUsername = readEnv("BIBER_USERNAME");
  const biberPassword = readEnv("BIBER_PASSWORD");

  if (!appBaseUrl || !canonicalDomain) {
    test.skip(
      true,
      "Auth-less role (no APP_BASE_URL / CANONICAL_DOMAIN) — persona scenario collapsed.",
    );
    return;
  }

  await page.context().clearCookies();

  await gotoOnion(page,`${appBaseUrl}/`, { waitUntil: "domcontentloaded" }).catch(() => {});

  const oidcEnabled = safeIsEnabled("sso");

  let keycloakRoundTripCompleted = false;
  if (biberUsername && biberPassword) {
    if (oidcEnabled && !page.url().includes("openid-connect/auth")) {
      const strictLogin = page
        .getByRole("link", { name: /^\s*(log\s*in|sign\s*in|login|sso)\s*$/i })
        .or(page.getByRole("button", { name: /^\s*(log\s*in|sign\s*in|login|sso)\s*$/i }))
        .first();
      const looseLogin = page
        .getByRole("link", { name: /log\s*in|sign\s*in|sso/i })
        .or(page.getByRole("button", { name: /log\s*in|sign\s*in|sso/i }))
        .first();
      await clickOidcLoginLink(page, strictLogin, looseLogin);
    }
    if (page.url().includes("openid-connect/auth")) {
      await performKeycloakLogin(page, biberUsername, biberPassword, canonicalDomain);
      keycloakRoundTripCompleted = true;
    }
  }

  await assertCspInjections(page, { isEnabled: safeIsEnabled });

  const authMarker = (surface) =>
    surface
      .getByRole("button", { name: /log\s*out|sign\s*out|sign-out|abmelden/i })
      .or(surface.getByRole("link", { name: /log\s*out|sign\s*out|sign-out|abmelden/i }))
      .or(surface.getByRole("menuitem", { name: /log\s*out|sign\s*out|sign-out|abmelden/i }))
      .or(surface.getByRole("button", { name: /(account|profile|user.?menu|^menu$|signed\s*in)/i }))
      .or(surface.getByRole("link", { name: /(account|profile|user.?menu|^menu$|signed\s*in)/i }))
      .or(
        surface.locator(
          "[data-region='user-menu-toggle'], .user-menu-toggle, .usermenu, [aria-label*='user menu' i], [aria-label*='account' i], [data-testid*='user' i], a[href*='logout' i], a[href*='end_session' i], a[href*='end-session' i]",
        ),
      );
  let reachedAuthenticated = keycloakRoundTripCompleted
    && new URL(page.url()).hostname.endsWith(canonicalDomain);
  if (!reachedAuthenticated) {
    reachedAuthenticated = await authMarker(page)
      .first()
      .isVisible({ timeout: resolveTimeout(15_000) })
      .catch(() => false);
  }
  if (!reachedAuthenticated) {
    for (const frame of page.frames()) {
      if (frame === page.mainFrame()) continue;
      const fUrl = frame.url();
      if (!fUrl || fUrl === "about:blank") continue;
      if (await authMarker(frame).first().isVisible({ timeout: resolveTimeout(1_000) }).catch(() => false)) {
        reachedAuthenticated = true;
        break;
      }
    }
  }
  if (!reachedAuthenticated) {
    for (const frame of page.frames()) {
      if (frame === page.mainFrame()) continue;
      const fUrl = frame.url();
      if (!fUrl || fUrl === "about:blank") continue;
      if (/openid-connect\/auth|\/oauth2\/(?:start|sign_in|callback)/.test(fUrl)) continue;
      if (canonicalDomain && fUrl.includes(canonicalDomain)) {
        reachedAuthenticated = true;
        break;
      }
      if (appBaseUrl && fUrl.startsWith(appBaseUrl)) {
        reachedAuthenticated = true;
        break;
      }
    }
  }
  if (reachedAuthenticated) {
    const loginStillVisible = await page
      .getByRole("link", { name: /log\s*in|sign\s*in|sso/i })
      .or(page.getByRole("button", { name: /log\s*in|sign\s*in|sso/i }))
      .first()
      .isVisible({ timeout: resolveTimeout(2_000) })
      .catch(() => false);
    if (loginStillVisible) {
      expect(
        false,
        `biber's OIDC login did NOT establish a session on ${canonicalDomain}: the ` +
          `round-trip returned to the app but a Login control is still visible — the ` +
          `code→token exchange did not complete (over Tor this is usually the OIDC ` +
          `adapter/token timeout in personas/utils/keycloak.js, not a logout problem). ` +
          `Current URL: ${page.url()}.`,
      ).toBe(true);
      return;
    }
  }
  if (!reachedAuthenticated) {
    expect(
      false,
      `biber did NOT reach an authenticated surface on ${canonicalDomain}. ` +
        `Either the role's auth chain is broken (OIDC mapping, post-login UI, logout button) ` +
        `or biber legitimately has no access here, in which case the role MUST declare ` +
        `\`PERSONA_BIBER_BLOCKED=true\` in templates/playwright.env.j2. ` +
        `Current URL: ${page.url()}.`,
    ).toBe(true);
    return;
  }

  await runRoleInteraction(page, { canonicalDomain, roleInteraction: opts.biberInteraction });

  await inAppLogout(page);
  await assertUnauthenticatedLanding(page, appBaseUrl);
}

module.exports = { runBiberFlow };
