// Native Pixelfed login/logout for the bootstrapped administrator account.
//
// This test drives pixelfed's stock `/login` form (email + password + CSRF
// hidden `_token` input + remember checkbox) — exactly as shipped by the
// upstream `zknt/pixelfed` docker image, no infinito-specific customisation.
// It complements the OIDC scenarios by exercising Laravel's classic
// session-cookie auth path so we still notice a native-login regression
// (form layout, CSRF middleware, user table credentials) even when the
// OIDC flow is intentionally disabled or broken.
//
// Required env (rendered by templates/playwright.env.j2):
//   PIXELFED_BASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD

const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");

  const pixelfedBaseUrl = shared.env.pixelfedBaseUrl;
  const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");
  const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

  test("pixelfed native login (administrator email+password)", async ({ page }) => {
    test.skip(
      shared.env.oidcEnabled,
      "Native login is only exercised when OIDC is disabled — when OIDC is on, pixelfed's `/login` redirects to the SSO entry and the OIDC tests own the journey.",
    );
    expect(pixelfedBaseUrl, "PIXELFED_BASE_URL must be set").toBeTruthy();
    expect(adminEmail, "ADMIN_EMAIL must be set in the Playwright env file").toBeTruthy();
    expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();

    const expectedBaseUrl = pixelfedBaseUrl.replace(/\/$/, "");
    const loginUrl = `${expectedBaseUrl}/login`;

    // 1. Land on the upstream `/login` form and confirm the stock layout.
    await gotoOnion(page, loginUrl);
    const emailField = page.locator('input#email[name="email"]');
    const passwordField = page.locator('input#password[name="password"]');
    const submitButton = page.locator('button[type="submit"], input[type="submit"]').first();
    const csrfInput = page.locator('input[name="_token"]');
    await expect(emailField).toBeVisible({ timeout: resolveTimeout(60_000) });
    await expect(passwordField).toBeVisible({ timeout: resolveTimeout(60_000) });
    await expect(csrfInput).toHaveCount(1);

    // 2. Fill the credentials and submit. The upstream form does the CSRF
    //    submission for us; we just type into the visible inputs.
    await emailField.fill(adminEmail);
    await passwordField.fill(adminPassword);
    await submitButton.click({ timeout: resolveTimeout(30_000) });

    // 3. Successful native auth lands on `/` (or `/i/web`) — never back on
    //    `/login`. Wait for the URL to leave `/login` and the authenticated
    //    UI surface to render.
    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(60_000),
        message: `Expected native login to leave ${loginUrl} for an authenticated pixelfed surface`,
      })
      .not.toMatch(/\/login(\?|$)/);

    const userMenu = page
      .locator('a[title="User Menu"], a[aria-haspopup="true"], a[href="/settings/home"], a[href="/logout"]')
      .first();
    await expect(userMenu).toBeVisible({ timeout: resolveTimeout(60_000) });

    // 4. Logout via pixelfed's native `/logout` POST route. Stock pixelfed
    //    exposes a Logout form (CSRF-guarded) under the User Menu; rendering
    //    the menu's dropdown can be flaky in headless mode, so we submit
    //    the POST directly with the page's current CSRF cookie.
    const csrfToken = await page.evaluate(() => {
      const meta = document.querySelector('meta[name="csrf-token"]');
      return meta ? meta.getAttribute("content") : null;
    });
    expect(csrfToken, "Expected authenticated pixelfed page to expose csrf-token meta tag").toBeTruthy();
    await page.evaluate(
      async ({ logoutUrl, token }) => {
        const form = document.createElement("form");
        form.method = "POST";
        form.action = logoutUrl;
        const csrf = document.createElement("input");
        csrf.type = "hidden";
        csrf.name = "_token";
        csrf.value = token;
        form.appendChild(csrf);
        document.body.appendChild(form);
        form.submit();
      },
      { logoutUrl: `${expectedBaseUrl}/logout`, token: csrfToken },
    );

    // 5. Verify we're back on the login form (logged out).
    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(60_000),
        message: "Expected pixelfed to return to a logged-out state after /logout POST",
      })
      .toMatch(/\/(login)?(\?|$|#)/);
    await expect(emailField.or(page.locator('a[href="/login"]'))).toBeVisible({ timeout: resolveTimeout(30_000) });
  });
};
