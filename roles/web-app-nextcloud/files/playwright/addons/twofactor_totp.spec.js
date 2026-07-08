const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

// twofactor_totp is a self-contained TOTP 2FA provider app (no partner service;
// its enabled gate only restricts it to native-login deployments). The loader
// runs `occ app:enable twofactor_totp`, but enabling the app is not the same as
// the integration being COUPLED: the coupling is that the app actually
// registered the `totp` provider in Nextcloud's two-factor provider registry,
// which is what the addon hook (tasks/addons/twofactor_totp.yml) verifies via
// `occ twofactorauth:state`. A registered provider is browser-observable on the
// personal Security settings page, which renders the TOTP enrollment section
// ("Authenticator app" / "TOTP") ONLY when the provider is live. This spec
// asserts that section exists, so it FAILS if the provider is not wired (even
// if the app row happened to be installed).
test("twofactor_totp addon: TOTP provider is registered and offered for enrollment", async ({ browser }) => {
  skipUnlessAddonEnabled("twofactor_totp");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    // 1) The app must be enabled: its config namespace is reachable through the
    // authenticated session. The installed-apps list resolves only when the
    // settings backend recognizes the app id.
    const appsUrl = new URL("settings/apps/installed", shared.env.nextcloudBaseUrl).toString();
    await gotoOnion(page, appsUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
    await shared.dismissBlockingNextcloudModals(page, page);

    const appEntry = page
      .locator('#app-twofactor_totp, [data-id="twofactor_totp"], a[href*="twofactor_totp"]')
      .first();
    await expect(
      appEntry,
      "the twofactor_totp app must appear as installed/enabled in the admin apps list",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    // 2) Coupling assertion: open the personal Security settings page. Nextcloud
    // renders a two-factor enrollment block per REGISTERED provider. The TOTP
    // provider surfaces an "Authenticator app" / "TOTP" section with an enable
    // toggle. If the provider were not registered (app present but not coupled
    // into the 2FA registry) this section is absent — so this expectation FAILS
    // when the integration is not wired.
    const securityUrl = new URL("settings/user/security", shared.env.nextcloudBaseUrl).toString();
    await gotoOnion(page, securityUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
    await shared.dismissBlockingNextcloudModals(page, page);

    await expect(
      page.locator("#app-content, #app-content-vue, #content, #content-vue").first(),
      "the Nextcloud personal Security settings page must render",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const appContent = page
      .locator("#app-content, #app-content-vue, #content, #content-vue")
      .first();

    const totpSection = page
      .locator(
        '[data-provider-id="totp"], #twofactor-totp, .twofactor-totp, ' +
          'section:has-text("Authenticator app"), fieldset:has-text("Authenticator app"), ' +
          'div:has-text("Use a third-party authenticator")',
      )
      .first();
    const totpEnrollment = appContent.getByText(/authenticator app/i).first();

    const sectionVisible = await totpSection
      .waitFor({ state: "visible", timeout: resolveTimeout(45_000) })
      .then(() => true)
      .catch(() => false);
    const enrollmentVisible = await totpEnrollment
      .waitFor({ state: "visible", timeout: resolveTimeout(15_000) })
      .then(() => true)
      .catch(() => false);

    expect(
      sectionVisible || enrollmentVisible,
      "the Security page must offer the TOTP enrollment section, proving the " +
        "twofactor_totp provider is registered in the 2FA provider registry " +
        "(addon coupling), not merely that the app is installed",
    ).toBeTruthy();
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
