const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

// Functional cross-role coupling check for nextcloud/integration_discourse.
//
// The upstream app declares ONLY a Personal section (Settings/Personal.php
// getSection() => 'connected-accounts'; no Admin class), so it surfaces on the
// user's "Connected accounts" page and mounts its Vue app on `#discourse_prefs`
// (src/personalSettings.js). That mount + the app-specific chrome it renders
// (the "Discourse instance address" field, the
// `web+nextclouddiscourse://auth-redirect` protocol note and "Register protocol
// handler" button) only exist when `occ app:enable integration_discourse` ran,
// so they are the positive enabled signal — their absence FAILS the test.
//
// The hard cross-role coupling is the per-user Discourse User-API-Key handoff.
// Personal.php provisions a per-user `client_id` and an app RSA `public_key`
// and seeds them into the `user-config` initial state. PersonalSettings.vue's
// `onOAuthClick` redirects the browser to
//   <instance>/user-api-key/new?client_id=<provisioned>&auth_redirect=web+nextclouddiscourse://auth-redirect
//     &application_name=Nextclouddiscourseintegration&nonce=<n>&public_key=<provisioned>&scopes=read,write,notifications
// i.e. it must REACH the partner Discourse host carrying the provisioned
// client_id + public_key. The instance address (`state.url`) is per-user and
// empty for an unconnected admin, so the spec types the deployed partner URL
// (DISCOURSE_BASE_URL, = the same `url.base` the addon provisions into the app)
// into the field to enable the connect control, then drives it and asserts the
// redirect lands on the partner host's /user-api-key/new — distinct from
// Nextcloud — with the provisioned client_id and public_key. That partner
// round-trip is the coupling signal; if the integration is not wired it cannot
// happen and the test FAILS.
test("integration integration_discourse: Nextcloud drives the User-API-Key connect to the partner Discourse", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_discourse");
  test.setTimeout(resolveTimeout(240_000));

  const unquote = (v) => ((v || "").trim().replace(/^"(.*)"$/, "$1"));
  const partnerBaseUrl = unquote(process.env.DISCOURSE_BASE_URL);
  expect(
    partnerBaseUrl,
    "DISCOURSE_BASE_URL must be rendered into the Playwright env so the spec can drive the connect flow at the real web-app-discourse partner host"
  ).toBeTruthy();

  const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
  const partnerHost = new URL(partnerBaseUrl).host;
  expect(
    partnerHost,
    "the deployed Discourse partner host must be distinct from the Nextcloud host"
  ).not.toBe(nextcloudHost);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    await gotoOnion(page,
      new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page).catch(() => {});

    // ENABLED SIGNAL: the integration's Vue app mounts on #discourse_prefs only
    // while integration_discourse is enabled. The bundle emits the mount
    // <div id="discourse_prefs"> and a Vue root carrying the same id, so pin to
    // .first() to avoid a strict-mode multiple-match. Absence here means the app
    // is disabled / not wired — that MUST fail the test, not skip it.
    const section = page.locator("#discourse_prefs").first();
    await expect(
      section,
      "the integration_discourse mount point (#discourse_prefs) must render on connected-accounts (app installed + enabled)"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    // The bundle rendered its inner content container, proving the frontend
    // actually booted (not just an empty section stub).
    await expect(
      section.locator("#discourse-content"),
      "the integration_discourse Vue app must render its #discourse-content block"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    // The fixed User-API-Key scaffolding strings the integration ships. These
    // come ONLY from this integration's bundle, so they fail if it is not wired.
    await expect(
      section.locator("text=web+nextclouddiscourse://auth-redirect"),
      "the integration_discourse protocol-handler redirect URI must be rendered in the settings"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
    await expect(
      section.getByRole("button", { name: /register protocol handler/i }),
      "the integration_discourse 'Register protocol handler' control must render"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    // The "Discourse instance address" NcTextField is emitted only by this
    // integration's component; it must be present and editable for an
    // unconnected account (the connect target the User-API-Key grant uses).
    const urlField = section.locator("input[type='url'], input[type='text']").first();
    await expect(
      urlField,
      "the integration_discourse 'Discourse instance address' field must render and be editable"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    // HARD COUPLING: type the deployed partner URL into the instance field. This
    // makes showOAuth (state.url && !connected) true so the "Connect to
    // Discourse" control (#discourse-oauth) renders. onInput saves the url via
    // /apps/integration_discourse/config; the connect click then redirects to
    // <partner>/user-api-key/new with the provisioned client_id + public_key.
    await urlField.click();
    await urlField.fill(partnerBaseUrl);
    await urlField.blur();

    const connect = section
      .locator("#discourse-oauth")
      .or(section.getByRole("button", { name: /connect to discourse/i }))
      .first();
    await expect(
      connect,
      "the 'Connect to Discourse' control must render once the instance address is set (integration provisioned the per-user client_id + app public_key)"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const popupPromise = page.waitForEvent("popup", { timeout: resolveTimeout(15_000) }).catch(() => null);
    await Promise.all([
      page.waitForEvent("framenavigated", { timeout: resolveTimeout(60_000) }).catch(() => {}),
      connect.click({ timeout: resolveTimeout(30_000) }),
    ]);

    const popup = await popupPromise;
    const currentUrl = () => (popup ? popup.url() : page.url());

    await expect
      .poll(currentUrl, { timeout: resolveTimeout(60_000) })
      .toMatch(/\/user-api-key\/new\?/i);

    const authorizeUrl = new URL(currentUrl());
    expect(
      authorizeUrl.host,
      "the Discourse User-API-Key authorize must be served by the partner instance, not Nextcloud"
    ).not.toBe(nextcloudHost);
    expect(
      authorizeUrl.host,
      "the connect redirect must land on the deployed Discourse partner host"
    ).toBe(partnerHost);
    expect(
      authorizeUrl.searchParams.get("client_id"),
      "the User-API-Key request must carry the provisioned per-user client_id"
    ).toBeTruthy();
    expect(
      authorizeUrl.searchParams.get("public_key"),
      "the User-API-Key request must carry the provisioned app RSA public_key"
    ).toBeTruthy();
    expect(authorizeUrl.searchParams.get("auth_redirect")).toBe(
      "web+nextclouddiscourse://auth-redirect"
    );
    expect(authorizeUrl.searchParams.get("scopes")).toBe("read,write,notifications");

    if (popup) await popup.close().catch(() => {});
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
