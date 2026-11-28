const { test } = require("@playwright/test");
const { gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  const { env, keycloakLogin, expect } = shared;

  async function assertDenied(page, targetUrl) {
    const [callback] = await Promise.all([
      page.waitForResponse((response) => new URL(response.url()).pathname === "/oauth2/callback", {
        timeout: resolveTimeout(120_000),
      }),
      (async () => {
        await gotoOnion(page, targetUrl, { waitUntil: "domcontentloaded" });
        await keycloakLogin(page, env.biberUsername, env.biberPassword);
      })(),
    ]);
    expect(
      callback.status(),
      `oauth2-proxy MUST refuse biber at ${targetUrl}: sso.oauth2.allowed_groups admits only the SeaweedFS administrator role group`
    ).toBe(403);
    expect(
      new URL(page.url()).pathname,
      `Expected biber to stay on the oauth2-proxy refusal, never on a SeaweedFS page (at ${page.url()})`
    ).toBe("/oauth2/callback");
  }

  test("biber: denied on Filer and Master (admin-only)", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    await assertDenied(page, env.filerUrl);
    await page.context().clearCookies();
    await assertDenied(page, env.masterUrl);
  });
};
