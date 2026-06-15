/**
 * `administrator` persona: single-app authenticated journey.
 *
 *   appBaseUrl → (OIDC if applicable) → admin-only interaction
 *              → CSP injection check → in-app logout
 *              → unauthenticated landing assertion.
 *
 * The administrator persona is now scoped to the role under test only.
 * Cross-service surface checks (prometheus, matomo, dashboard tile
 * reachability) are owned by the dedicated provider specs:
 *
 *   - `roles/web-app-dashboard/files/playwright/playwright.spec.js` parameterises
 *     dashboard-tile reachability per consumer role.
 *   - `roles/web-app-prometheus/files/playwright/playwright.spec.js` parameterises
 *     scrape-target presence + admin reach + biber denial.
 *   - `roles/web-app-matomo/files/playwright/playwright.spec.js` parameterises
 *     tracker-site presence + admin reach + biber denial.
 *
 * Each role's persona scenario therefore visits its OWN canonical URL
 * directly (no dashboard tile click) and exercises only that role.
 */

const { test, expect } = require("@playwright/test");
const {
  normalizeUrl,
  readEnv,
  safeIsEnabled,
  performKeycloakLogin,
  clickOidcLoginLink,
  inAppLogout,
  assertUnauthenticatedLanding,
  assertCspInjections,
  runRoleInteraction,
} = require("./utils");

async function runAdminFlow(page, opts = {}) {
  // Explicit role contract opt-out. Roles that
  // genuinely have no OIDC-driven admin surface (auth-provider roles,
  // bespoke local-only admin paths, mobile-first SPAs whose logout
  // control is unreachable to the generic helper, ...) declare
  // `PERSONA_ADMINISTRATOR_BLOCKED=true` in
  // `templates/playwright.env.j2` with a documented rationale in the
  // role's TODO.md or README.md.
  if ((process.env.PERSONA_ADMINISTRATOR_BLOCKED || "").toLowerCase() === "true") {
    test.skip(
      true,
      `administrator persona is explicitly blocked by the role contract (PERSONA_ADMINISTRATOR_BLOCKED=true). See the role's TODO.md for the rationale and the path back to a runnable journey.`,
    );
    return;
  }

  // Test B parity: the SSO-proxy sidecar (or in-app OIDC) gates the
  // initial redirect chain, universal-logout rewrites the in-app
  // logout click, and the shared CSP-injection helper
  // (`assertCspInjections`) gates on `matomo` to verify every role's
  // CSP allows the matomo tracker host when matomo is enabled. All
  // three are consumed by the persona surface; reference them via
  // safeIsEnabled with literal arguments so the env-gate parity guard
  // recognises them as consumed by the spec via the shared persona
  // helper.
  safeIsEnabled("sso");
  safeIsEnabled("logout");
  safeIsEnabled("matomo");

  const canonicalDomain = readEnv("CANONICAL_DOMAIN");
  const appBaseUrl = normalizeUrl(process.env.APP_BASE_URL);
  const adminUsername = readEnv("ADMIN_USERNAME");
  const adminPassword = readEnv("ADMIN_PASSWORD");

  // Persona-collapse exception: roles whose env does not
  // expose APP_BASE_URL or CANONICAL_DOMAIN are auth-less by
  // construction; skip cleanly rather than fail.
  if (!appBaseUrl || !canonicalDomain) {
    test.skip(
      true,
      "Auth-less role (no APP_BASE_URL / CANONICAL_DOMAIN) — persona scenario collapsed.",
    );
    return;
  }

  await page.context().clearCookies();

  const oidcEnabled = safeIsEnabled("sso");

  // Direct-app entry: bookmark-style navigation. The OAuth2-Proxy gate
  // fires on the first request, redirecting unauthenticated requests
  // to Keycloak; the auth chain is the same regardless of how the user
  // arrived at the URL.
  await page.goto(`${appBaseUrl}/`, { waitUntil: "domcontentloaded" }).catch(() => {});

  // Two auth shapes share a single login step:
  //   * oauth2-proxy gate: the goto is intercepted and the page lands
  //     directly on the Keycloak auth endpoint; perform Keycloak login.
  //   * In-app OIDC plugin: the role's own UI exposes a Login link;
  //     click it to trigger the redirect, then perform Keycloak login.
  let keycloakRoundTripCompleted = false;
  if (adminUsername && adminPassword) {
    if (oidcEnabled && !page.url().includes("openid-connect/auth")) {
      // Two-pass: strict anchored regex targets the role's OWN Login button
      // (e.g. nextcloud's plain `<a>Login</a>`); loose substring regex covers
      // roles whose Login link gets a Bootstrap tooltip
      // (`data-bs-toggle="tooltip"` moves `title` into
      // `data-bs-original-title`, which the accessibility tree pulls into the
      // link's accessible name — anchored regex misses such links). The
      // `\s*` between `log` and `in` keeps both patterns from matching
      // `Logout`/`logoff`.
      const strictLogin = page
        .getByRole("link", { name: /^\s*(log\s*in|sign\s*in|login|sso|admin)\s*$/i })
        .or(page.getByRole("button", { name: /^\s*(log\s*in|sign\s*in|login|sso|admin)\s*$/i }))
        .first();
      const looseLogin = page
        .getByRole("link", { name: /log\s*in|sign\s*in|sso|admin/i })
        .or(page.getByRole("button", { name: /log\s*in|sign\s*in|sso|admin/i }))
        .first();
      await clickOidcLoginLink(page, strictLogin, looseLogin);
    }
    if (page.url().includes("openid-connect/auth")) {
      await performKeycloakLogin(page, adminUsername, adminPassword, canonicalDomain);
      keycloakRoundTripCompleted = true;
    }
  }

  // No-SSO fallback: with SSO disabled the OIDC step above is a no-op, so if
  // the role renders its own username/password form, drive it with the admin
  // credentials (the app's native auth is the only path without SSO).
  if (!oidcEnabled && adminUsername && adminPassword) {
    const passwordField = page.locator("input[type='password']").first();
    if (await passwordField.isVisible({ timeout: 10_000 }).catch(() => false)) {
      const usernameField = page
        .locator(
          "input[name='username'], input[name='email'], input[name='login'], input[type='email'], input[autocomplete='username']",
        )
        .first();
      if (await usernameField.isVisible().catch(() => false)) {
        await usernameField.fill(adminUsername).catch(() => {});
      }
      await passwordField.fill(adminPassword).catch(() => {});
      await page
        .getByRole("button", { name: /log\s*in|sign\s*in|login|submit/i })
        .or(page.locator("button[type='submit'], input[type='submit']"))
        .first()
        .click()
        .catch(() => {});
      await page.waitForLoadState("networkidle").catch(() => {});
    }
  }

  // Verify administrator actually reached an authenticated surface.
  // The persona contract demands a full app → logout journey. When
  // the post-OIDC page does NOT expose a logout control / user menu,
  // that is a real regression UNLESS the role explicitly declares the
  // admin persona blocked via env flag
  // `PERSONA_ADMINISTRATOR_BLOCKED=true`. Without that flag the test
  // fails loudly so a real regression cannot hide behind a silent
  // skip.
  const adminAuthMarker = (surface) =>
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
  // A successful Keycloak round-trip (oauth2-proxy-gated login that
  // returned to `canonicalDomain` after the form submit) is a strong
  // proof of authentication on its own — some roles (oauth2-proxy
  // gated services such as Prometheus, status pages, raw upstream UIs
  // without their own account menu) have no in-app auth marker to
  // probe. When the round-trip ran, treat the persona as authenticated
  // and let `inAppLogout` decide whether a logout control is
  // reachable. The `adminAuthMarker` poll below still tries to find a
  // visible Account/Logout control so the post-login UI assertions
  // remain effective for roles that DO expose one.
  let adminReachedAuthenticated = keycloakRoundTripCompleted
    && new URL(page.url()).hostname.endsWith(canonicalDomain);
  if (!adminReachedAuthenticated) {
    adminReachedAuthenticated = await adminAuthMarker(page)
      .first()
      .isVisible({ timeout: 15_000 })
      .catch(() => false);
  }
  if (!adminReachedAuthenticated) {
    for (const frame of page.frames()) {
      if (frame === page.mainFrame()) continue;
      const fUrl = frame.url();
      if (!fUrl || fUrl === "about:blank") continue;
      if (await adminAuthMarker(frame).first().isVisible({ timeout: 1_000 }).catch(() => false)) {
        adminReachedAuthenticated = true;
        break;
      }
    }
  }
  if (!adminReachedAuthenticated) {
    // URL-based fallback for NESTED frames only: see biber.js — the
    // main frame can park on the canonical domain without an
    // authenticated session, so URL alone is not proof of auth.
    for (const frame of page.frames()) {
      if (frame === page.mainFrame()) continue;
      const fUrl = frame.url();
      if (!fUrl || fUrl === "about:blank") continue;
      if (/openid-connect\/auth|\/oauth2\/(?:start|sign_in|callback)/.test(fUrl)) continue;
      if (canonicalDomain && fUrl.includes(canonicalDomain)) {
        adminReachedAuthenticated = true;
        break;
      }
      if (appBaseUrl && fUrl.startsWith(appBaseUrl)) {
        adminReachedAuthenticated = true;
        break;
      }
    }
  }
  if (!adminReachedAuthenticated) {
    expect(
      false,
      `administrator did NOT reach an authenticated surface on ${canonicalDomain}. ` +
        `Either the role's auth chain is broken or administrator legitimately has no OIDC-driven admin path here, ` +
        `in which case the role MUST declare \`PERSONA_ADMINISTRATOR_BLOCKED=true\` in templates/playwright.env.j2. ` +
        `Current URL: ${page.url()}.`,
    ).toBe(true);
    return;
  }

  await assertCspInjections(page, { isEnabled: safeIsEnabled });

  // Drive a real, app-specific interaction after login. Specs SHOULD
  // override the default by passing an `adminInteraction` callback that
  // exercises an admin-only surface (admin panel, realm settings, ...).
  await runRoleInteraction(page, { canonicalDomain, roleInteraction: opts.adminInteraction });

  await inAppLogout(page);
  await assertUnauthenticatedLanding(page, appBaseUrl);
}

module.exports = { runAdminFlow };
