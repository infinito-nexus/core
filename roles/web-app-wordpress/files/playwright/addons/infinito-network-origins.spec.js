const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { resolveTimeout } = require("../timeouts");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test("addon infinito-network-origins: the site links within the network it is served on", async ({
  browser,
}) => {
  skipUnlessAddonEnabled("infinito-network-origins");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await gotoOnion(page, `${shared.env.wpBaseUrl}/`, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });

    const restLink = await page
      .locator('link[rel="https://api.w.org/"]')
      .getAttribute("href", { timeout: resolveTimeout(30_000) });

    expect(
      new URL(restLink).origin,
      "WordPress builds its REST discovery link from home; a link into another network's sibling means home was not served from the origin the request arrived on"
    ).toBe(new URL(shared.env.wpBaseUrl).origin);
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
