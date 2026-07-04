const { test, expect } = require("@playwright/test");

const { assertCspResponseHeader, assertCspMetaParity } = require("./personas");

exports.register = function (shared) {
  test("guest: Jellyfin web reachable, serves CSP, never reaches an authenticated surface", async ({ page }) => {
    const response = await page.goto(`${shared.env.jellyfinBaseUrl}/web/`);
    expect(response, "Expected a Jellyfin web response").toBeTruthy();
    expect(response.status(), "Expected Jellyfin web status to be < 400").toBeLessThan(400);
    expect(
      response.url().includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" to back the Jellyfin URL`,
    ).toBe(true);

    const directives = assertCspResponseHeader(response, "jellyfin web");
    await assertCspMetaParity(page, directives, "jellyfin web");

    await expect
      .poll(() => shared.onLoginSurface(page), {
        timeout: 30_000,
        message: "guest must remain on the Jellyfin login surface",
      })
      .toBe(true);
    await expect(page.locator(".headerUserButton")).toHaveCount(0);
  });
};
