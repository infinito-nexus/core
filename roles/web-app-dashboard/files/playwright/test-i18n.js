const { test, expect } = require("./fixtures/onion-test");

const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");

function catalogue(raw) {
  return JSON.parse(decodeDotenvQuotedValue(raw || "") || "{}");
}

function normalized(text) {
  return (text || "").replace(/\s+/g, " ");
}

async function pageText(page, path) {
  const response = await gotoOnion(page, path);
  expect(response, `Expected a response for ${path}`).toBeTruthy();
  expect(response.status(), `Expected ${path} to load`).toBeLessThan(400);
  return normalized(await page.locator("body").textContent());
}

function translatedOn(english, german, entries) {
  return Object.entries(entries).filter(
    ([source, target]) =>
      source !== target && english.includes(normalized(source)) && german.includes(normalized(target)),
  );
}

exports.register = function () {
  test("the German dashboard shows translated card descriptions and menu categories", async ({ page }) => {
    const cards = catalogue(process.env.DASHBOARD_I18N_CARDS_DE_JSON);
    const menu = catalogue(process.env.DASHBOARD_I18N_MENU_DE_JSON);
    expect(Object.keys(menu).length, "Expected German menu translations in the core catalog").toBeGreaterThan(0);

    const english = await pageText(page, "/");
    const german = await pageText(page, "/de/");

    expect(await page.locator("html").getAttribute("lang")).toBe("de");
    expect(
      translatedOn(english, german, cards).length,
      "Expected at least one card description in German on /de/",
    ).toBeGreaterThan(0);
    expect(
      translatedOn(english, german, menu).length,
      "Expected at least one menu category in German on /de/",
    ).toBeGreaterThan(0);
  });
};
