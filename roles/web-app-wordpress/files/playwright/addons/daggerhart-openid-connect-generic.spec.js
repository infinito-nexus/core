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
const admin = shared.env.adminUsername;
const usersPath = shared.env.multisiteEnabled
  ? "/wp-admin/network/users.php"
  : "/wp-admin/users.php";

async function signInAsAdministrator(page) {
  await shared.wpAdminLoginViaOidc(
    page,
    shared.env.wpBaseUrl,
    admin,
    shared.env.adminPassword
  );
  await expect(page, "Expected to land in wp-admin after the OIDC round-trip").toHaveURL(
    /\/wp-admin\/?/,
    { timeout: resolveTimeout(30_000) }
  );
  await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/profile.php`, {
    waitUntil: "domcontentloaded",
  });
  await expect(
    page.locator("#user_login"),
    `Expected the OIDC round-trip to sign in as the WordPress user "${admin}"`
  ).toHaveValue(admin, { timeout: resolveTimeout(30_000) });
}

async function accountsNamedLikeAdministrator(page) {
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
  return (await loginLinks.allTextContents()).map((login) => login.trim()).sort();
}

test("addon daggerhart-openid-connect-generic: administrator OIDC login lands in wp-admin", async ({ browser }) => {
  skipUnlessAddonEnabled("daggerhart-openid-connect-generic");
  skipUnlessServiceEnabled("sso");

  const observer = await browser.newContext({ ignoreHTTPSErrors: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const observerPage = await observer.newPage();
  const page = await context.newPage();

  try {
    await signInAsAdministrator(observerPage);
    const before = await accountsNamedLikeAdministrator(observerPage);
    expect(before, `Expected ${usersPath} to list "${admin}"`).toContain(admin);

    await signInAsAdministrator(page);

    expect(
      await accountsNamedLikeAdministrator(observerPage),
      `Expected the OIDC login to create no account on ${usersPath}`
    ).toEqual(before);
  } finally {
    await page.close().catch(() => {});
    await observerPage.close().catch(() => {});
    await context.close().catch(() => {});
    await observer.close().catch(() => {});
  }
});
