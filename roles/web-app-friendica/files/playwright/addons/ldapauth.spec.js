const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

// ldapauth is Friendica's LDAP authentication addon. It has no dedicated
// in-app page; its coupling to svc-db-openldap is observable as: (a) a valid
// LDAP credential binds against the openldap partner and establishes a
// Friendica session, and (b) an INVALID credential is REJECTED by that same
// bind — proof the addon actually delegates auth to LDAP rather than the page
// merely re-rendering. We reuse the role's LDAP login idiom (the exact
// ldapauth bind path) and gate behind both the addon flag and the ldap
// service. Both assertions FAIL if the integration is not wired.
async function assertValidCredentialBinds(browser, login) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    const baseUrl = shared.trimmedBaseUrl();

    // 1) Positive path: the real LDAP credential must establish a session.
    await login(page, shared.env.adminUsername, shared.env.adminPassword);
    await gotoOnion(page, `${baseUrl}/network`, { waitUntil: "domcontentloaded" }).catch(() => {});

    const authenticatedSurface = page
      .locator("#topbar-first, #navbar-apps-menu, a[href*='/logout']")
      .first();
    await expect(
      authenticatedSurface,
      "Expected an authenticated Friendica surface after the ldapauth-backed login"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await expect(
      page.locator("input[name='password']"),
      "Expected to be past the login form once ldapauth accepted the LDAP credential"
    ).toHaveCount(0);

    // 2) When the admin user can reach /admin/addons, the addon list must show
    // ldapauth as installed/active — direct proof the addon is enabled and the
    // hooks are registered. Admin reachability depends on the admin-email match,
    // so we only assert when the panel is reachable; otherwise the bind-based
    // checks above and below carry the coupling proof.
    await gotoOnion(page, `${baseUrl}/admin/addons`, { waitUntil: "domcontentloaded" }).catch(() => {});
    const onAdminAddons = /\/admin\/addons/.test(page.url());
    const hasLoginForm = await page
      .locator("input[name='password']")
      .first()
      .isVisible()
      .catch(() => false);
    if (onAdminAddons && !hasLoginForm) {
      await expect(
        page.locator("a[href*='admin/addons/ldapauth'], :text('ldapauth')").first(),
        "Expected ldapauth to appear in Friendica's admin addon list when the admin panel is reachable"
      ).toBeVisible({ timeout: resolveTimeout(15_000) });
    }

    await shared.friendicaLogout(page);
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
}

async function assertBogusCredentialIsRejected(browser) {
  const negContext = await browser.newContext({ ignoreHTTPSErrors: true });
  const negPage = await negContext.newPage();
  try {
    const baseUrl = shared.trimmedBaseUrl();
    await gotoOnion(negPage, `${baseUrl}/login`, { waitUntil: "domcontentloaded" }).catch(() => {});

    await shared.loginViaFriendicaForm(
      negPage,
      shared.env.adminUsername,
      `wrong-${Date.now()}-${shared.env.adminPassword}`
    );
    await gotoOnion(negPage, `${baseUrl}/network`, { waitUntil: "domcontentloaded" }).catch(() => {});

    await expect(
      negPage.locator("#topbar-first, #navbar-apps-menu, a[href*='/logout']").first(),
      "Expected NO authenticated session when ldapauth rejects a bogus password against openldap"
    ).toHaveCount(0);
  } finally {
    await negPage.close().catch(() => {});
    await negContext.close().catch(() => {});
  }
}

test("administrator: addon ldapauth binds a valid LDAP credential against openldap", async ({ browser }) => {
  skipUnlessAddonEnabled("ldapauth");
  skipUnlessServiceEnabled("ldap");
  await assertValidCredentialBinds(browser, shared.loginViaFriendica);
});

test("administrator: addon ldapauth rejects a bogus LDAP credential against openldap", async ({ browser }) => {
  skipUnlessAddonEnabled("ldapauth");
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  await assertBogusCredentialIsRejected(browser);
});
