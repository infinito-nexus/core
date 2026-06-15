const { test } = require("@playwright/test");

exports.register = function (shared) {
  const { env, keycloakLogin, isAuthChain, expect } = shared;

  async function assertDenied(page, targetUrl) {
    const response = await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
    if (isAuthChain(page.url())) {
      await keycloakLogin(page, env.biberUsername, env.biberPassword);
    }
    await page.waitForLoadState("networkidle").catch(() => {});
    const status = response ? response.status() : 0;
    const body = (await page.locator("body").innerText().catch(() => "")) || "";
    const onAppHost = page.url().includes(new URL(targetUrl).host) && !isAuthChain(page.url());
    const forbidden = status === 403 || /forbidden|not a member|unauthorized|access denied/i.test(body);
    expect(
      forbidden || !onAppHost,
      `biber (non-admin) must be denied at ${targetUrl}`
    ).toBe(true);
  }

  test("biber: denied on Filer and Master (admin-only)", async ({ page }) => {
    test.skip(!env.ssoEnabled, "SSO disabled");
    await assertDenied(page, env.filerUrl);
    await page.context().clearCookies();
    await assertDenied(page, env.masterUrl);
  });
};
