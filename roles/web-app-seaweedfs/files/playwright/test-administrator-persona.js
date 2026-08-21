const { test } = require("@playwright/test");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  const { env, keycloakLogin, isAuthChain, expect } = shared;

  test("administrator: can log in and reach both Filer and Master UIs", async ({ page }) => {
    test.skip(!env.frontendEnabled, "frontend disabled (headless backend node)");
    test.skip(!env.ssoEnabled, "SSO disabled");

    await gotoOnion(page, env.filerUrl, { waitUntil: "domcontentloaded" });
    if (isAuthChain(page.url())) {
      await keycloakLogin(page, env.adminUsername, env.adminPassword);
    }
    await page.waitForLoadState("networkidle").catch(() => {});

    expect(isAuthChain(page.url()), "admin must land back on the Filer UI").toBe(false);
    expect(page.url()).toContain(new URL(env.filerUrl).host);
    const filerBody = (await page.locator("body").innerText().catch(() => "")) || "";
    expect(filerBody.length, "Filer UI must render content").toBeGreaterThan(0);

    await gotoOnion(page, env.masterUrl, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle").catch(() => {});
    expect(isAuthChain(page.url()), "admin must reach the Master UI without re-auth").toBe(false);
    expect(page.url()).toContain(new URL(env.masterUrl).host);
    const masterBody = (await page.locator("body").innerText().catch(() => "")) || "";
    expect(masterBody, "Master UI must show SeaweedFS cluster status").toMatch(/volume|topology|cluster|seaweed/i);
  });
};
