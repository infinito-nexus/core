const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion, isOnionUrl, requireDotenvValue } = require("../personas");
const shared = require("../_shared");

test("addon freedomtranslate-wp: WordPress translates through the deployed gateway", async ({ browser, playwright }) => {
  skipUnlessAddonEnabled("freedomtranslate-wp");
  skipUnlessServiceEnabled("translate");
  test.setTimeout(resolveTimeout(180_000));

  const endpoint = `${shared.env.translateBaseUrl}/translate`;
  const partnerHost = requireDotenvValue(process.env.TRANSLATE_PARTNER_HOST, "TRANSLATE_PARTNER_HOST");
  expect(
    new URL(shared.env.translateBaseUrl).host,
    "the gateway must be a distinct host, not WordPress itself",
  ).not.toBe(new URL(shared.env.wpBaseUrl).host);

  const proxyServer = process.env.PLAYWRIGHT_PROXY;
  const gateway = await playwright.request.newContext({
    ignoreHTTPSErrors: true,
    ...(proxyServer
      ? {
          proxy: {
            server: proxyServer,
            ...(isOnionUrl(endpoint) ? {} : { bypass: new URL(endpoint).hostname }),
          },
        }
      : {}),
  });
  try {
    const translated = await gateway.fetch(endpoint, {
      method: "POST",
      data: { q: "House", source: "en", target: "de", format: "text" },
      headers: { "Content-Type": "application/json" },
      failOnStatusCode: false,
      timeout: resolveTimeout(120_000),
    });
    expect(translated.status(), `Expected the endpoint WordPress posts to (${endpoint}) to translate`).toBe(200);
    expect((await translated.json()).translatedText, "Expected a translation from the gateway").toBeTruthy();
  } finally {
    await gateway.dispose();
  }

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  try {
    await shared.wpAdminLoginViaOidc(page, shared.env.wpBaseUrl, shared.env.adminUsername, shared.env.adminPassword);

    await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/options-general.php?page=freedomtranslate`, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });

    const urlField = page.locator('input[name="freedomtranslate_api_url"], input[id*="freedomtranslate_api_url"]').first();
    await expect(urlField, "Expected the FreedomTranslate API URL field in wp-admin").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    const configured = new URL(await urlField.inputValue());
    expect(configured.host, "Expected the plugin to post to the deployed gateway").toBe(partnerHost);
    expect(configured.pathname, "Expected the plugin to post to the gateway's translate route").toBe("/translate");
  } finally {
    await context.close();
  }
});
