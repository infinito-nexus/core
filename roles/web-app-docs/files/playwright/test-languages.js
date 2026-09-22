const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const sample = JSON.parse(decodeDotenvQuotedValue(process.env.DOCS_I18N_DE_SAMPLE_JSON || "") || "{}");

function normalized(text) {
  return (text || "").replace(/\s+/g, " ");
}

async function statusOf(request, url) {
  const response = await request.get(url, { failOnStatusCode: false, maxRedirects: 0, timeout: resolveTimeout(30_000) });
  return response.status();
}

exports.register = function (shared) {
  test("the deployed working tree is published in German with a language switcher", async ({ page, request }) => {
    test.setTimeout(resolveTimeout(5_400_000)); // the English and then the German Sphinx build of the deployed working tree
    expect(Object.keys(sample).length, "Expected German translations of README messages in docs.po").toBeGreaterThan(0);
    await expect
      .poll(() => statusOf(request, `${shared.appBaseUrl}/deployed/de/`), {
        message: "Expected the German site of the deployed working tree to be built",
        timeout: resolveTimeout(5_300_000),
        intervals: [30_000],
      })
      .toBe(200);

    await gotoOnion(page, `${shared.appBaseUrl}/deployed/de/`);
    expect(await page.locator("html").getAttribute("lang")).toBe("de");
    const text = normalized(await page.locator("body").textContent());
    expect(
      Object.values(sample).some((target) => text.includes(normalized(target))),
      "Expected a German README message on /deployed/de/",
    ).toBe(true);

    const switcher = page.locator("#docs-language-switcher");
    await expect(switcher.locator("option", { hasText: "Deutsch" })).toHaveCount(1, { timeout: resolveTimeout(30_000) });
    await expect(switcher.locator("option", { hasText: "English" })).toHaveCount(1);
    await Promise.all([
      page.waitForURL(`${shared.appBaseUrl}/deployed/index.html`, { timeout: resolveTimeout(30_000) }),
      switcher.selectOption({ label: "English" }),
    ]);
  });

  test("a language without a translated site answers 404", async ({ request }) => {
    test.setTimeout(resolveTimeout(3_000_000)); // the English Sphinx build of the deployed working tree
    await expect
      .poll(() => statusOf(request, `${shared.appBaseUrl}/deployed/aa/`), {
        message: "Expected the Afar path of the deployed working tree to answer 404",
        timeout: resolveTimeout(2_900_000),
        intervals: [30_000],
      })
      .toBe(404);
  });
};
