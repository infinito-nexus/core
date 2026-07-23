const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test("addon wp-discourse: WordPress bridge is provisioned for and reaches the partner Discourse", async ({ browser }) => {
  skipUnlessAddonEnabled("wp-discourse");
  skipUnlessServiceEnabled("discourse");
  test.setTimeout(resolveTimeout(120_000));

  const wpHost = new URL(shared.env.wpBaseUrl).host;
  const discourseHost = new URL(shared.env.discourseBaseUrl).host;
  expect(
    discourseHost,
    "the partner Discourse host must be distinct from the WordPress host"
  ).not.toBe(wpHost);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.wpAdminLoginViaOidc(
      page,
      shared.env.wpBaseUrl,
      shared.env.adminUsername,
      shared.env.adminPassword
    );

    await gotoOnion(page,
      `${shared.env.wpBaseUrl}/wp-admin/admin.php?page=wp_discourse_options&tab=connection`,
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );

    const settingsSurface = page
      .locator(
        "form#wp-discourse-form, .wp-discourse-options, #wpbody-content .wrap, .nav-tab-wrapper"
      )
      .filter({ hasText: /discourse/i })
      .first();
    await expect(
      settingsSurface,
      "Expected the WP Discourse settings surface in wp-admin"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    const urlField = page
      .locator(
        'input[name="discourse_connect[url]"], input[id*="discourse_connect"][id*="url"], input[name*="discourse_connect"][name*="url"]'
      )
      .first();
    await expect(
      urlField,
      "the WP Discourse connection tab must render the provisioned Discourse base-URL field — its absence means the bridge config never landed"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    const configuredUrl = (await urlField.inputValue().catch(() => "")) || "";
    expect(
      /^https?:\/\//i.test(configuredUrl),
      "WordPress must have the partner Discourse base URL provisioned in the wp-discourse plugin (proves the bridge config landed)"
    ).toBe(true);
    const configuredHost = new URL(configuredUrl).host;
    expect(
      configuredHost,
      "the provisioned Discourse connect URL must point at the partner Discourse host, not the WordPress host"
    ).toBe(discourseHost);
    expect(configuredHost).not.toBe(wpHost);

    const sessionResp = await shared.discourseApiRequest(
      context.request,
      "/session/current.json"
    );
    expect(
      sessionResp.ok(),
      `WordPress's provisioned Discourse API credentials must authenticate against the PARTNER Discourse host ${discourseHost} (GET /session/current.json). A non-OK response means the bridge cannot reach/authenticate to the partner — the coupling failed.`
    ).toBe(true);
    expect(
      new URL(sessionResp.url()).host,
      "the authenticated Discourse session round-trip must be served by the partner instance, not WordPress"
    ).toBe(discourseHost);

    const sessionBody = await sessionResp.json();
    const sessionUsername = sessionBody?.current_user?.username || "";
    expect(
      sessionUsername.toLowerCase(),
      "the partner Discourse must resolve the bridge's provisioned publishing user (publish-username 'system'), proving the WP->Discourse API key is the real coupling"
    ).toBe((shared.env.discourseApiUsername || "system").toLowerCase());
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
