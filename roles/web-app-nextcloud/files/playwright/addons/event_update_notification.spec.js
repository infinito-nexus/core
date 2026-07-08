const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("event_update_notification addon: app is registered as an enabled app in the Nextcloud app registry", async ({ browser }) => {
  skipUnlessAddonEnabled("event_update_notification");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const enabledAppsUrl = new URL(
      "ocs/v2.php/cloud/apps?filter=enabled&format=json",
      shared.env.nextcloudBaseUrl,
    ).toString();
    const enabledAppsResponse = await page.request.get(enabledAppsUrl, {
      headers: { "OCS-APIRequest": "true", Accept: "application/json" },
    });
    expect(
      enabledAppsResponse.ok(),
      "the Provisioning OCS enabled-apps endpoint must respond to the authenticated session",
    ).toBeTruthy();

    const enabledAppsBody = await enabledAppsResponse.json();
    const enabledApps = enabledAppsBody?.ocs?.data?.apps;
    expect(
      Array.isArray(enabledApps),
      "the OCS enabled-apps response must carry an ocs.data.apps array",
    ).toBeTruthy();
    expect(
      enabledApps,
      "the OCS app registry must list 'event_update_notification' among the ENABLED apps; " +
        "its absence proves the addon is not installed/enabled (broken coupling), " +
        "which must FAIL rather than silently pass",
    ).toContain("event_update_notification");

    const disabledAppsUrl = new URL(
      "ocs/v2.php/cloud/apps?filter=disabled&format=json",
      shared.env.nextcloudBaseUrl,
    ).toString();
    const disabledAppsResponse = await page.request.get(disabledAppsUrl, {
      headers: { "OCS-APIRequest": "true", Accept: "application/json" },
    });
    expect(
      disabledAppsResponse.ok(),
      "the Provisioning OCS disabled-apps endpoint must respond to the authenticated session",
    ).toBeTruthy();
    const disabledApps = (await disabledAppsResponse.json())?.ocs?.data?.apps;
    expect(
      Array.isArray(disabledApps) ? disabledApps : [],
      "'event_update_notification' must not appear in the DISABLED app list while the addon is enabled",
    ).not.toContain("event_update_notification");
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
