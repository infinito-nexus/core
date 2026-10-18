const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test("addon freedomtranslate-wp: WordPress translates through the deployed gateway", async ({ browser, request }) => {
  skipUnlessAddonEnabled("freedomtranslate-wp");
  skipUnlessServiceEnabled("translate");
  test.setTimeout(resolveTimeout(180_000));

  const endpoint = `${shared.env.translateBaseUrl}/translate`;
  expect(
    new URL(shared.env.translateBaseUrl).host,
    "the gateway must be a distinct host, not WordPress itself",
  ).not.toBe(new URL(shared.env.wpBaseUrl).host);

  const translated = await request.fetch(endpoint, {
    method: "POST",
    data: { q: "House", source: "en", target: "de", format: "text" },
    headers: { "Content-Type": "application/json" },
    failOnStatusCode: false,
    timeout: resolveTimeout(120_000),
  });
  expect(translated.status(), `Expected the endpoint WordPress posts to (${endpoint}) to translate`).toBe(200);
  expect((await translated.json()).translatedText, "Expected a translation from the gateway").toBeTruthy();

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
    expect(await urlField.inputValue(), "Expected the plugin to post to the deployed gateway").toBe(endpoint);
  } finally {
    await context.close();
  }
});
