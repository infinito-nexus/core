const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

// Cross-role coupling check for the upstream nextcloud/integration_moodle app.
//
// Reality of the app (confirmed against upstream source):
//   - PersonalSettings.vue renders `#moodle_prefs` with the `#moodle-url`
//     instance-address input (v-model state.url), `#moodle-login`,
//     `#moodle-password`, and a "Connect to Moodle" button that only appears
//     once BOTH login and password are typed (showConnect = login && password).
//   - Typing into `#moodle-url` debounce-saves the per-user url via PUT /config.
//   - Clicking Connect runs onValidate() -> POST /apps/integration_moodle/get-token
//     {login,password}. MoodleAPIController::getToken uses the PER-USER url
//     (getUserValue('url')) to call the partner Moodle webservice token endpoint
//     ({url}/login/token.php). On success it returns 200 {user_name}; on a
//     refused login it returns 401 {error}. Either verdict proves the request
//     reached the PARTNER Moodle host server-side (not Nextcloud, not a config
//     stub) — that is the real bridge coupling.
//
// This spec drives that coupling end to end: it pins the per-user url to the
// deployed partner Moodle base URL, then connects and asserts the get-token
// response is a partner auth verdict. The only allowed skip is the top-level
// skipUnlessAddonEnabled gate; the addon flag is false unless the web-app-moodle
// partner is deployed, so when this body runs the partner exists and the section
// MUST render (its absence is a real coupling failure and fails the test).
test("integration integration_moodle: per-user get-token connect reaches the partner Moodle token endpoint", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_moodle");
  test.setTimeout(120_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
    const partnerBaseUrl = (shared.env.moodleBaseUrl || "").trim();
    expect(
      /^https?:\/\//i.test(partnerBaseUrl),
      "MOODLE_BASE_URL must resolve to the deployed partner Moodle base URL when integration_moodle is enabled"
    ).toBeTruthy();
    const partnerHost = new URL(partnerBaseUrl).host;
    expect(
      partnerHost,
      "the Moodle partner host must be distinct from the Nextcloud host"
    ).not.toBe(nextcloudHost);

    await shared.loginToStandaloneNextcloud(page);

    await page.goto(
      new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: 60_000 }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const section = page.locator("#moodle_prefs");
    await expect(
      section.first(),
      "the integration_moodle personal settings section (#moodle_prefs) must render — its absence means the app failed to enable/provision when the partner is deployed"
    ).toBeVisible({ timeout: 60_000 });

    const urlField = section.locator("#moodle-url");
    await expect(
      urlField.first(),
      "the Moodle instance-address field (#moodle-url) must render in the connect form"
    ).toBeVisible({ timeout: 30_000 });

    const configSavePromise = page.waitForResponse(
      (response) =>
        /\/apps\/integration_moodle\/config$/.test(new URL(response.url()).pathname) &&
        response.request().method() === "PUT",
      { timeout: 30_000 }
    );
    await urlField.first().fill(partnerBaseUrl);
    await urlField.first().blur().catch(() => {});
    const configSave = await configSavePromise;
    expect(
      configSave.ok(),
      "pinning #moodle-url to the partner base URL must persist via PUT /config (per-user url the get-token call will use)"
    ).toBeTruthy();

    await section.locator("#moodle-login").fill(shared.env.loginUsername);
    await section.locator("#moodle-password").fill(shared.env.loginPassword);

    const connect = section.getByRole("button", { name: /connect to moodle/i });
    await expect(
      connect.first(),
      "the 'Connect to Moodle' control must render once login and password are entered (per-user get-token grant entry point)"
    ).toBeVisible({ timeout: 30_000 });

    const getTokenPromise = page.waitForResponse(
      (response) =>
        /\/apps\/integration_moodle\/get-token$/.test(new URL(response.url()).pathname) &&
        response.request().method() === "POST",
      { timeout: 60_000 }
    );
    await connect.first().click();
    const getTokenResponse = await getTokenPromise;

    const status = getTokenResponse.status();
    const body = await getTokenResponse.json().catch(() => ({}));

    expect(
      [200, 401].includes(status),
      `the get-token call must resolve to a partner Moodle auth verdict (200 connected or 401 refused login), got ${status} ${JSON.stringify(body)} — a different status means the request never reached the partner token endpoint`
    ).toBeTruthy();

    if (status === 200) {
      expect(
        body.user_name,
        "a successful get-token must return the authenticated Moodle user_name minted by the partner webservice"
      ).toBeTruthy();
      await expect(
        section.getByText(/connected as/i),
        "the panel must flip to a connected state after the partner minted a webservice token"
      ).toBeVisible({ timeout: 30_000 });
      await expect(section.locator("#moodle-rm-cred")).toBeVisible({ timeout: 30_000 });
    } else {
      expect(
        body.error,
        "a refused get-token must surface the partner Moodle token-endpoint error, proving the request reached the partner rather than failing on missing/unpinned url"
      ).toBeTruthy();
    }
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
