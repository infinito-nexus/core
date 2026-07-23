const { test, expect } = require("@playwright/test");

const { isServiceEnabled } = require("./service-gating");
const {
  appBaseUrl,
  oidcIssuerUrl,
  biberUsername,
  biberPassword,
  attachDiagnostics,
  setupMatomoPage,
  loginAsAdmin,
} = require("./_shared");
const { expectNoCspViolations } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async ({ page }) => {
  await setupMatomoPage(page);
});

test("matomo local administrator logs in and logs out", async ({ page }) => {
  const diagnostics = attachDiagnostics(page);

  await loginAsAdmin(page);

  await expect(page.locator("body")).toContainText(/dashboard|websites|matomo/i, { timeout: 60_000 });

  await page.goto(`${appBaseUrl}/index.php?module=Login&action=logout`);

  await expect
    .poll(
      async () =>
        (await page
          .locator("input#login_form_login, input[name='form_login']")
          .first()
          .count()
          .catch(() => 0)) > 0,
      {
        timeout: 60_000,
        message: "Expected Matomo login form to reappear after logout"
      }
    )
    .toBe(true);

  await expectNoCspViolations(page, diagnostics, "matomo administrator login");
});

// Biber denial at Matomo: biber's Keycloak account exists but is NOT in
// `web-app-matomo-administrator`. After the OIDC chain, oauth2-proxy MUST
// refuse the session, either with a 403 at `/oauth2/callback` or by redirecting
// to a denial surface. This is the SPOT for "biber cannot reach Matomo" since
// the persona helper no longer drives this probe.
test("matomo: biber is denied access at the admin surface", async ({ browser }) => {
  test.skip(
    !isServiceEnabled("sso"),
    "matomo's oauth2-proxy gate is not wired yet (services.yml oauth2.enabled=false; see TODO).",
  );
  test.skip(
    !oidcIssuerUrl || !biberUsername || !biberPassword,
    "OIDC_ISSUER_URL / BIBER_USERNAME / BIBER_PASSWORD must be set in the Playwright env file",
  );

  const expectedOidcAuthUrl = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const expectedMatomoBaseUrl = appBaseUrl.replace(/\/$/, "");

  const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const biberPage = await biberContext.newPage();

    // Register the callback listener BEFORE goto so no response is missed; the
    // redirect chain may complete before a listener registered after login.
    const callbackResponsePromise = biberPage
      .waitForResponse(
        (res) => res.url().includes("/oauth2/callback"),
        { timeout: 60_000 },
      )
      .catch(() => null);

    await biberPage.goto(`${expectedMatomoBaseUrl}/`);

    await expect
      .poll(() => biberPage.url(), {
        timeout: 30_000,
        message: `Expected redirect to Keycloak OIDC auth: ${expectedOidcAuthUrl}`,
      })
      .toContain(expectedOidcAuthUrl);

    const usernameField = biberPage
      .getByRole("textbox", { name: /username|email/i })
      .or(biberPage.locator("input[name='username'], input#username"))
      .first();
    const passwordField = biberPage
      .getByRole("textbox", { name: /^password$/i })
      .or(biberPage.locator("input[name='password'], input#password"))
      .first();
    const signInButton = biberPage
      .getByRole("button", { name: /sign in|login|log in/i })
      .or(biberPage.locator("input#kc-login, button#kc-login, button[type='submit'], input[type='submit']"))
      .first();

    await usernameField.waitFor({ state: "visible", timeout: 60_000 });
    await usernameField.fill(biberUsername);
    await usernameField.press("Tab").catch(() => {});
    await passwordField.fill(biberPassword);
    await signInButton.click();

    const callbackResponse = await callbackResponsePromise;

    if (callbackResponse) {
      // Primary path: the proxy returns 403 at /oauth2/callback. Anything below
      // 400 means biber crossed into the admin surface and is a real regression.
      expect(
        callbackResponse.status(),
        `oauth2-proxy MUST deny biber at /oauth2/callback (got ${callbackResponse.status()})`,
      ).toBeGreaterThanOrEqual(400);
      return;
    }

    // Fallback: no callback observed; verify the URL did not settle on the
    // authenticated Matomo surface, AND the body does not expose admin markers.
    await biberPage.waitForLoadState("domcontentloaded", { timeout: 60_000 }).catch(() => {});
    const finalUrl = biberPage.url();
    const onAuthDenialChain =
      /openid-connect\/auth/.test(finalUrl) ||
      /\/oauth2\/(?:start|sign_in|callback)/.test(finalUrl);

    if (onAuthDenialChain) return;

    const probe = await biberPage.request
      .get(`${expectedMatomoBaseUrl}/`, { ignoreHTTPSErrors: true, maxRedirects: 0 })
      .catch(() => null);
    if (!probe) {
      expect(
        false,
        `biber must NOT reach the matomo UI (probe failed; outer URL ${finalUrl})`,
      ).toBe(true);
      return;
    }
    const status = probe.status();
    if (status === 401 || status === 403) return;
    if (status >= 300 && status < 400) {
      const location = probe.headers()["location"] || "";
      if (/openid-connect\/auth|\/oauth2\/(?:start|sign_in|callback)/.test(location)) return;
      return;
    }
    if (status === 200) {
      const body = await probe.text().catch(() => "");
      const showsAdminUi =
        /id=['"]?Dashboard_/i.test(body) &&
        (/id=['"]?Settings/i.test(body) || /class=['"][^'"]*activeNav/i.test(body));
      if (showsAdminUi) {
        expect(
          false,
          `biber must NOT reach the matomo UI: GET ${expectedMatomoBaseUrl}/ returned 200 with admin DOM markers.`,
        ).toBe(true);
        return;
      }
      // Pre-auth or login-form surface is acceptable: biber sees matomo's login
      // but is NOT past it.
      const isMatomoSurface =
        /<input[^>]*name=['"]?form_login['"]?/i.test(body) ||
        /<input[^>]*name=['"]?form_password['"]?/i.test(body) ||
        /piwik|matomo/i.test(body);
      expect(
        isMatomoSurface,
        `biber probe to ${expectedMatomoBaseUrl}/ returned 200 but the body is neither matomo's login form nor a recognisable matomo / piwik surface.`,
      ).toBe(true);
      return;
    }
    expect(
      false,
      `biber probe to ${expectedMatomoBaseUrl}/ returned unexpected status ${status}.`,
    ).toBe(true);
  } finally {
    await biberContext.close().catch(() => {});
  }
});
