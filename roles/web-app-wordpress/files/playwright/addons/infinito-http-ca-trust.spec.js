const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");

test("addon infinito-http-ca-trust: the CA-trust mu-plugin is loaded by WordPress and outbound HTTPS calls resolve", async ({
  browser,
}) => {
  skipUnlessAddonEnabled("infinito-http-ca-trust");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(120_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.wpAdminLoginViaOidc(
      page,
      shared.env.wpBaseUrl,
      shared.env.adminUsername,
      shared.env.adminPassword
    );

    await page.goto(
      `${shared.env.wpBaseUrl}/wp-admin/plugins.php?plugin_status=mustuse`,
      { waitUntil: "domcontentloaded", timeout: 60_000 }
    );

    await expect(
      page.locator("#the-list"),
      "the Must-Use plugins screen must list the CA-trust mu-plugin under the Plugin Name its header declares — one absent from this screen was never copied into wp-content/mu-plugins"
    ).toContainText("Infinito.Nexus HTTP CA Trust", { timeout: 30_000 });

    const restResponse = await page.request.get(
      `${shared.env.wpBaseUrl}/wp-json/`,
      { failOnStatusCode: false }
    );
    expect(
      restResponse.status(),
      "the REST root must answer over HTTPS: WordPress reaching its own TLS endpoint is what this mu-plugin's CA bundle enables"
    ).toBe(200);
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
