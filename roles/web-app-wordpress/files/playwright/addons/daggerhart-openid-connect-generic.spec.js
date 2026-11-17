const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

// daggerhart-openid-connect-generic is WordPress's OIDC login plugin: it
// has no dedicated user-facing page. Its observable surface is that the
// role's existing administrator OIDC login idiom (wpAdminLoginViaOidc →
// Keycloak round-trip → wp-admin) succeeds. We REUSE that idiom rather
// than reimplement OIDC mechanics, gating behind the addon flag and the
// sso service.
test("addon daggerhart-openid-connect-generic: administrator OIDC login lands in wp-admin", async ({ browser }) => {
  skipUnlessAddonEnabled("daggerhart-openid-connect-generic");
  skipUnlessServiceEnabled("sso");

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.wpAdminLoginViaOidc(
      page,
      shared.env.wpBaseUrl,
      shared.env.adminUsername,
      shared.env.adminPassword
    );

    await expect(page, "Expected to land in wp-admin after the OIDC round-trip").toHaveURL(
      /\/wp-admin\/?/,
      { timeout: resolveTimeout(30_000) }
    );

    const admin = shared.env.adminUsername;
    await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/profile.php`, {
      waitUntil: "domcontentloaded",
    });
    await expect(
      page.locator("#user_login"),
      `Expected the OIDC round-trip to sign in as the WordPress user "${admin}"`
    ).toHaveValue(admin, { timeout: resolveTimeout(30_000) });

    const usersPath = shared.env.multisiteEnabled
      ? "/wp-admin/network/users.php"
      : "/wp-admin/users.php";
    await gotoOnion(
      page,
      `${shared.env.wpBaseUrl}${usersPath}?s=${encodeURIComponent(admin)}`,
      { waitUntil: "domcontentloaded" }
    );
    const loginLinks = page.locator("#the-list .column-username strong a");
    await expect(
      loginLinks.first(),
      `Expected ${usersPath} to list "${admin}"`
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
    const logins = (await loginLinks.allTextContents()).map((login) => login.trim());
    const escaped = admin.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    expect(logins, `Expected ${usersPath} to list "${admin}"`).toContain(admin);
    expect(
      logins.filter((login) => new RegExp(`^${escaped}\\d+$`, "i").test(login)),
      `Expected no second account named "${admin}" plus a digit on ${usersPath}`
    ).toEqual([]);
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
