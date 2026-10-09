const { test, expect } = require("@playwright/test");

const { apiGetOnion, gotoOnion } = require("./personas");
const { isServiceEnabled, skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("guest: the dashboard hands an anonymous visitor to a sign-in page", async ({ page }) => {
    skipUnlessServiceEnabled("webui");
    await page.context().clearCookies();
    const response = await gotoOnion(page, `${shared.env.baseUrl}/`);
    expect(response.status(), "Expected the sign-in page to answer without a server error").toBeLessThan(500);
    await expect(
      page.locator("form.provider-form, a.provider-btn, #kc-form-login").first(),
      "Expected a sign-in form or an identity provider button",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
    await expect(page.locator("#app-sidebar"), "Expected no dashboard shell without a session").toHaveCount(0);

    const sessions = await apiGetOnion(page.request, `${shared.env.baseUrl}/api/sessions`, {
      maxRedirects: 0,
      timeout: resolveTimeout(30_000),
    });
    expect(
      [302, 401, 403],
      "Expected the dashboard API to refuse or redirect a request without a session",
    ).toContain(sessions.status());
  });

  test("administrator: dashboard sign-in → configuration → sign-out", async ({ page }) => {
    skipUnlessServiceEnabled("webui");
    await shared.signIn(page);

    await page.locator("#app-sidebar a[href$='/config']").click();
    await expect(page.locator("header[role='banner'] h1")).toHaveText(/config/i, {
      timeout: resolveTimeout(60_000),
    });

    await page.getByRole("button", { name: "Log out" }).click();
    await expect(
      page.locator("form.provider-form, a.provider-btn").first(),
      "Expected the dashboard sign-in page after signing out",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
  });

  test("administrator: the dashboard refuses the password of the platform administrator", async ({ page }) => {
    skipUnlessServiceEnabled("webui");
    skipUnlessServiceDisabled("sso");
    await shared.openSignIn(page);
    const form = page.locator("form.provider-form");
    await form.locator("input[name='username']").fill(shared.env.adminUsername);
    await form.locator("input[name='password']").fill(shared.env.adminPassword);
    const [attempt] = await Promise.all([
      page.waitForResponse((response) => response.url().endsWith("/auth/password-login"), {
        timeout: resolveTimeout(30_000),
      }),
      form.locator("button[type='submit']").click(),
    ]);
    expect(
      attempt.status(),
      "Expected the dashboard to refuse the platform administrator password: the agent container must not hold it",
    ).toBe(401);
    await expect(page.locator("#app-sidebar"), "Expected no dashboard shell after a refused sign-in").toHaveCount(0);
  });

  test("guest: with the web UI off the subdomain root serves no dashboard and the API still answers", async ({
    request,
  }) => {
    skipUnlessServiceDisabled("webui");
    const base = shared.env.baseUrl;
    const timeout = resolveTimeout(30_000);

    const root = await apiGetOnion(request, `${base}/`, { maxRedirects: 0, timeout });
    expect(
      isServiceEnabled("sso") ? [301, 302, 303, 307, 308] : [404],
      "Expected the root to answer as the API server does: a redirect to the identity provider behind the OAuth2 proxy, 404 without it",
    ).toContain(root.status());
    expect(await root.text(), "Expected no dashboard document on the root").not.toContain('id="root"');

    const anonymous = await apiGetOnion(request, `${base}/v1/models`, { timeout });
    expect(anonymous.status(), "Expected /v1/models without the bearer key to be refused").toBe(401);

    const authenticated = await apiGetOnion(request, `${base}/v1/models`, {
      headers: { Authorization: `Bearer ${shared.env.apiServerKey}` },
      timeout,
    });
    expect(authenticated.status(), "Expected /v1/models with the bearer key to answer").toBe(200);
  });
};
