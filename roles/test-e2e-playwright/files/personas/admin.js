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
  if ((process.env.PERSONA_ADMINISTRATOR_BLOCKED || "").toLowerCase() === "true") {
    test.skip(
      true,
      `administrator persona is explicitly blocked by the role contract (PERSONA_ADMINISTRATOR_BLOCKED=true). See the role's TODO.md for the rationale and the path back to a runnable journey.`,
    );
    return;
  }

  safeIsEnabled("sso");
  safeIsEnabled("logout");
  safeIsEnabled("matomo");

  const canonicalDomain = readEnv("CANONICAL_DOMAIN");
  const appBaseUrl = normalizeUrl(process.env.APP_BASE_URL);
  const adminUsername = readEnv("ADMIN_USERNAME");
  const adminPassword = readEnv("ADMIN_PASSWORD");
  const adminNativePassword = readEnv("ADMIN_NATIVE_PASSWORD");

  if (!appBaseUrl || !canonicalDomain) {
    test.skip(
      true,
      "Auth-less role (no APP_BASE_URL / CANONICAL_DOMAIN) — persona scenario collapsed.",
    );
    return;
  }

  await page.context().clearCookies();

  const oidcEnabled = safeIsEnabled("sso");

  await page.goto(`${appBaseUrl}/`, { waitUntil: "domcontentloaded" }).catch(() => {});

  let keycloakRoundTripCompleted = false;
  if (adminUsername && adminPassword) {
    if (oidcEnabled && !page.url().includes("openid-connect/auth")) {
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

  let nativeLoginCompleted = false;
  if (!oidcEnabled && adminUsername && adminPassword) {
    const base = appBaseUrl.replace(/\/$/, "");
    const tryNativeLogin = async (probeTimeout = 5_000) => {
      const passwordField = page.locator("input[type='password']:visible").first();
      if (!(await passwordField.isVisible({ timeout: probeTimeout }).catch(() => false))) {
        return false;
      }
      const usernameField = page
        .locator(
          "input[name='username']:visible, input[name='email']:visible, input[name='login']:visible, input[type='email']:visible, input[autocomplete='username']:visible",
        )
        .first();
      if (await usernameField.isVisible().catch(() => false)) {
        await usernameField.fill(adminUsername).catch(() => {});
      }
      await passwordField.fill(adminNativePassword || adminPassword).catch(() => {});
      await passwordField.press("Enter").catch(() => {});
      await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
      if (await passwordField.isVisible({ timeout: 2_000 }).catch(() => false)) {
        await page
          .getByRole("button", { name: /log\s*in|sign\s*in|login|submit/i })
          .or(page.locator("button[type='submit'], input[type='submit']"))
          .first()
          .click()
          .catch(() => {});
        await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
      }
      return true;
    };

    let loginAttempted = await tryNativeLogin(10_000);
    if (!loginAttempted) {
      for (const loginPath of ["/login", "/admin/", "/admin"]) {
        await page.goto(`${base}${loginPath}`, { waitUntil: "domcontentloaded" }).catch(() => {});
        if (await tryNativeLogin()) {
          loginAttempted = true;
          break;
        }
      }
    }

    const passwordStillVisible = await page
      .locator("input[type='password']:visible")
      .first()
      .isVisible({ timeout: 2_000 })
      .catch(() => false);
    nativeLoginCompleted =
      loginAttempted &&
      !passwordStillVisible &&
      new URL(page.url()).hostname.endsWith(canonicalDomain);
  }

  const adminAuthMarker = (surface) =>
    surface
      .getByRole("button", { name: /log\s*out|sign\s*out|sign-out|abmelden/i })
      .or(surface.getByRole("link", { name: /log\s*out|sign\s*out|sign-out|abmelden/i }))
      .or(surface.getByRole("menuitem", { name: /log\s*out|sign\s*out|sign-out|abmelden/i }))
      .or(surface.getByRole("button", { name: /(profile|user.?menu|^menu$|signed\s*in)/i }))
      .or(surface.getByRole("link", { name: /(profile|user.?menu|^menu$|signed\s*in)/i }))
      .or(
        surface.locator(
          "[data-region='user-menu-toggle'], .user-menu-toggle, .usermenu, [aria-label*='user menu' i], [aria-label*='account' i], [data-testid*='user' i], a[href*='logout' i], a[href*='end_session' i], a[href*='end-session' i]",
        ),
      );
  let adminReachedAuthenticated =
    (keycloakRoundTripCompleted || nativeLoginCompleted) &&
    new URL(page.url()).hostname.endsWith(canonicalDomain);
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

  await runRoleInteraction(page, { canonicalDomain, roleInteraction: opts.adminInteraction });

  await inAppLogout(page);
  await assertUnauthenticatedLanding(page, appBaseUrl);
}

module.exports = { runAdminFlow };
