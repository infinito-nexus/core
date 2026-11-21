const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  apiGetOnion,
  gotoOnion,
  safeIsEnabled,
  expectHstsWhenTls,
  assertCspResponseHeader,
} = require("./personas");

exports.register = function (shared) {
  test("Map Animator front page answers on the canonical domain with a redirect to the login", async ({ request }) => {
    const response = await apiGetOnion(request, `${shared.env.appBaseUrl}/`, {
      failOnStatusCode: false,
      maxRedirects: 0,
      timeout: resolveTimeout(30_000),
    });
    expect([302, 303], "an anonymous front page request must be redirected").toContain(response.status());
    expect(response.url().includes(shared.env.canonicalDomain)).toBe(true);
    expect(response.headers().location || "", "the redirect must lead into the login").toMatch(
      safeIsEnabled("sso") ? /\/oauth2\/start|openid-connect\/auth/ : /^\/renders\/login\?next=/,
    );
  });

  test("Map Animator editor serves TLS and CSP and draws the map after login", async ({ page }) => {
    test.setTimeout(resolveTimeout(240_000)); // Keycloak round-trip, native login, and the first tiles from tiles.versatiles.org
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    await shared.loginToApp(page, shared.env.biberUsername, shared.env.biberPassword);
    const response = await gotoOnion(page, `${shared.env.appBaseUrl}/`, { waitUntil: "domcontentloaded" });
    expect(response, "Expected a Map Animator response").toBeTruthy();
    expect(response.status(), "Expected the editor to be served").toBe(200);
    expect(response.headers()["content-type"] || "").toContain("text/html");
    expectHstsWhenTls(response.headers(), shared.env.appBaseUrl, "Map Animator");
    assertCspResponseHeader(response, "Map Animator editor");
    await expect(
      page.locator("canvas.maplibregl-canvas"),
      "the editor must mount its MapLibre map",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await shared.logout(page);
  });
};
