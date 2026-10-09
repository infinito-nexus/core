const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const { baseUrl, fetchPluginRecord, loginAsAdministrator } = require("../jenkins-login");

test.use({ ignoreHTTPSErrors: true });

test("addon oic-auth: the OpenID Connect plugin backs the active security realm", async ({ page }) => {
  skipUnlessAddonEnabled("oic-auth");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));

  await loginAsAdministrator(page);

  const plugin = await fetchPluginRecord(page, "oic-auth");
  expect(
    plugin,
    "the plugin manager must list 'oic-auth'; it is absent when the addon declaration did not " +
      "reach templates/plugins.txt.j2 and jenkins-plugin-cli never fetched it",
  ).toBeTruthy();
  expect(plugin.active, "the oic-auth plugin must be active, not merely downloaded").toBe(true);

  await gotoOnion(page, `${baseUrl}/manage/configureSecurity/`, { waitUntil: "domcontentloaded" });
  const body = (await page.locator("body").innerText().catch(() => "")) || "";
  expect(
    body,
    "the security configuration must offer the OpenID Connect realm; its absence means casc " +
      "selected a realm the plugin does not provide",
  ).toMatch(/openid/i);
});
