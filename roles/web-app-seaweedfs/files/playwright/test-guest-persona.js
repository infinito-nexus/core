const { test } = require("@playwright/test");

exports.register = function (shared) {
  const { env, isAuthChain, expect } = shared;

  async function assertRedirectedToAuth(page, targetUrl) {
    await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle").catch(() => {});
    expect(
      isAuthChain(page.url()),
      `guest must be redirected to the auth chain at ${targetUrl}, got ${page.url()}`
    ).toBe(true);
  }

  test("guest: redirected to auth, never reaches Filer or Master", async ({ page }) => {
    test.skip(!env.ssoEnabled, "SSO disabled");
    await assertRedirectedToAuth(page, env.filerUrl);
    await page.context().clearCookies();
    await assertRedirectedToAuth(page, env.masterUrl);
  });
};
