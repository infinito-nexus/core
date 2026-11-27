/**
 * Cosmos sky assertions shared by every role spec whose role ships a
 * `templates/cosmos.css.j2`.
 *
 * - `COSMOS_SKY`: the selector of a document that draws the live sky.
 * - `TRANSPARENT`: the computed value of a cleared background color.
 * - `pinLegible(page, band)`: pins `data-cosmos-legible` to `all` or `top`
 *   and restores the pin whenever the sky's `refresh()` (its minute tick)
 *   rewrites it, until the next pin or navigation.
 * - `assertSky(page, cleared, blocks, label)`: waits for the live sky, then
 *   with the band pinned to `all` every `cleared` selector's first match has
 *   a transparent background and `body` takes `--cosmos-text`; with the band
 *   pinned to `top` `body` stays transparent and every `blocks` selector's
 *   first match takes `--design-surface-1` and `--design-text`. The band is
 *   left pinned to `all`.
 */

const { expect } = require("@playwright/test");

const { assertToken } = require("./design");
const { resolveTimeout } = require("./timeouts");

const COSMOS_SKY = "html[data-cosmos-mode='full']";
const TRANSPARENT = "rgba(0, 0, 0, 0)";

function pinLegible(page, band) {
  return page.evaluate((value) => {
    const root = document.documentElement;
    globalThis.cosmosLegiblePin?.disconnect();
    root.setAttribute("data-cosmos-legible", value);
    globalThis.cosmosLegiblePin = new MutationObserver(() => {
      if (root.getAttribute("data-cosmos-legible") !== value) root.setAttribute("data-cosmos-legible", value);
    });
    globalThis.cosmosLegiblePin.observe(root, { attributes: true, attributeFilter: ["data-cosmos-legible"] });
  }, band);
}

async function assertSky(page, cleared, blocks, label) {
  await page.locator(COSMOS_SKY).waitFor({ state: "attached", timeout: resolveTimeout(20_000) });
  await pinLegible(page, "all");
  for (const selector of cleared) {
    await expect
      .poll(() => page.locator(selector).first().evaluate((node) => getComputedStyle(node).backgroundColor), {
        message: `${label}: ${selector} must let the sky through`,
      })
      .toBe(TRANSPARENT);
  }
  await assertToken(page, "body", "color", "--cosmos-text", label);
  await pinLegible(page, "top");
  expect(
    await page.locator("body").evaluate((body) => getComputedStyle(body).backgroundColor),
    `${label} legible top: the body stays clear so the sky keeps drawing`,
  ).toBe(TRANSPARENT);
  for (const selector of blocks) {
    await assertToken(page, selector, "background-color", "--design-surface-1", `${label} legible top`);
    await assertToken(page, selector, "color", "--design-text", `${label} legible top`);
  }
  await pinLegible(page, "all");
}

module.exports = {
  COSMOS_SKY,
  TRANSPARENT,
  assertSky,
  pinLegible,
};
