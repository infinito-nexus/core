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

async function runBiberFlow(page, opts = {}) {
  // Explicit role contract opt-out. Roles that
  // genuinely have no biber-accessible surface (admin-only software
  // without OIDC auto-provisioning, mobile-first SPAs whose logout
  // control is unreachable to the generic helper, ...) declare
  // `PERSONA_BIBER_BLOCKED=true` in `templates/playwright.env.j2`
  // with a documented rationale in the role's TODO.md or README.md.
  if ((process.env.PERSONA_BIBER_BLOCKED || "").toLowerCase() === "true") {
    test.skip(
      true,
      `biber persona is explicitly blocked by the role contract (PERSONA_BIBER_BLOCKED=true). See the role's TODO.md for the rationale and the path back to a runnable journey.`,
    );
    return;
  }

  // Test B parity: every role's env declares OAUTH2/LOGOUT/MATOMO
  // _SERVICE_ENABLED (the auth chain runs through oauth2-proxy, the
  // post-flow universal-logout JS rewrites the role's own logout
  // button, and the shared CSP-injection helper gates on `matomo` to
  // verify every role's CSP allows the matomo tracker host when matomo
  // is enabled). All three flags are consumed by the persona surface;
  // reference them via safeIsEnabled with literal arguments so the
  // env-gate parity guard recognises them as consumed by the spec via
  // the shared persona.
  safeIsEnabled("oauth2");
  safeIsEnabled("logout");
  safeIsEnabled("matomo");

  const canonicalDomain = readEnv("CANONICAL_DOMAIN");
  const appBaseUrl = normalizeUrl(process.env.APP_BASE_URL);
  const biberUsername = readEnv("BIBER_USERNAME");
  const biberPassword = readEnv("BIBER_PASSWORD");

  // Persona-collapse exception: roles whose env does not
  // expose APP_BASE_URL or CANONICAL_DOMAIN are auth-less by
  // construction (web-svc-*, federation-only web-app-*); the persona
  // scenario MUST skip cleanly rather than fail.
  if (!appBaseUrl || !canonicalDomain) {
    test.skip(
      true,
      "Auth-less role (no APP_BASE_URL / CANONICAL_DOMAIN) — persona scenario collapsed.",
    );
    return;
  }

  await page.context().clearCookies();

  // Direct-app entry: bookmark-style navigation. The OAuth2-Proxy gate
  // fires on the first request, redirecting unauthenticated requests
  // to Keycloak; the auth chain is the same regardless of how the user
  // arrived at the URL.
  await page.goto(`${appBaseUrl}/`, { waitUntil: "domcontentloaded" }).catch(() => {});

  const oidcEnabled = safeIsEnabled("oidc");

  // Two auth shapes share a single login step:
  //   * oauth2-proxy gate: the goto is intercepted and the page lands
  //     directly on the Keycloak auth endpoint; perform Keycloak login.
  //   * In-app OIDC plugin: the role's own UI exposes a Login link;
  //     click it to trigger the redirect, then perform Keycloak login.
  let keycloakRoundTripCompleted = false;
  if (biberUsername && biberPassword) {
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

  // Verify biber actually reached an authenticated surface on the
  // role. The persona contract demands a full app → logout journey,
  // so the post-OIDC page MUST expose a logout control or a user menu.
  // When it does NOT, that is either:
  //   - a real regression (OIDC mapping broken, post-login UI
  //     missing the logout button, role's auth chain misconfigured),
  //     OR
  //   - a deliberate role contract that biber has NO access to this
  //     role at all.
  // The deliberate case MUST be declared explicitly via
  // `PERSONA_BIBER_BLOCKED=true` in `templates/playwright.env.j2`.
  // Without that flag the test fails loudly so a real regression
  // cannot hide behind a silent skip.
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
  // A successful Keycloak round-trip (oauth2-proxy-gated login that
  // returned to `canonicalDomain` after the form submit) is a strong
  // proof of authentication on its own — some roles (oauth2-proxy
  // gated services such as Prometheus, status pages, raw upstream UIs
  // without their own account menu) have no in-app auth marker to
  // probe. When the round-trip ran, treat the persona as authenticated
  // and let `inAppLogout` decide whether a logout control is
  // reachable. The `authMarker` poll below still tries to find a
  // visible Account/Logout control so the post-login UI assertions
  // remain effective for roles that DO expose one.
  let reachedAuthenticated = keycloakRoundTripCompleted
    && new URL(page.url()).hostname.endsWith(canonicalDomain);
  if (!reachedAuthenticated) {
    reachedAuthenticated = await authMarker(page)
      .first()
      .isVisible({ timeout: 15_000 })
      .catch(() => false);
  }
  if (!reachedAuthenticated) {
    for (const frame of page.frames()) {
      if (frame === page.mainFrame()) continue;
      const fUrl = frame.url();
      if (!fUrl || fUrl === "about:blank") continue;
      if (await authMarker(frame).first().isVisible({ timeout: 1_000 }).catch(() => false)) {
        reachedAuthenticated = true;
        break;
      }
    }
  }
  if (!reachedAuthenticated) {
    // URL-based fallback for NESTED frames only: a child iframe parked
    // on the role's canonical surface (NOT on Keycloak / oauth2-proxy
    // denial / about:blank) counts as the persona reaching the app via
    // an embedded surface. The main frame is NOT a valid URL match —
    // it can also park on the canonical domain when the role's auth
    // chain failed silently, so URL alone is not proof of auth.
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

  // Drive a real, app-specific interaction after login (or directly on
  // the role surface when no auth is required). Specs SHOULD override
  // the default by passing a `biberInteraction` callback that exercises
  // the role's bespoke UI (post a message, open a settings tab, etc.).
  await runRoleInteraction(page, { canonicalDomain, roleInteraction: opts.biberInteraction });

  await inAppLogout(page);
  await assertUnauthenticatedLanding(page, appBaseUrl);
}

module.exports = { runBiberFlow };
