const { test, expect } = require("@playwright/test");
const { expectHstsWhenTls, gotoOnion, ownResponseHeaders } = require("./personas");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("atmo appview renders under the canonical domain with TLS", async ({ page }) => {
    const response = await gotoOnion(page, `${shared.env.appBaseUrl}/`);
    expect(response, "Expected an atmo landing response").toBeTruthy();
    expect(response.status(), "Expected the atmo landing to answer 200").toBe(200);
    expect(
      response.url().includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" to back the atmo URL`
    ).toBe(true);
    expectHstsWhenTls(await ownResponseHeaders(response), shared.env.appBaseUrl, "atmo");
    await expect(
      page.locator("body.atmo"),
      "Expected the SvelteKit shell of atmo to render its body marker"
    ).toBeAttached({ timeout: resolveTimeout(30_000) });
  });
};
