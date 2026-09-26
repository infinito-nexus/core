const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const sample = JSON.parse(decodeDotenvQuotedValue(process.env.DOCS_I18N_DE_SAMPLE_JSON || "") || "{}");

function normalized(text) {
  return (text || "").replace(/\s+/g, " ");
}

let lastTransportError = null;

async function statusOf(request, url) {
  try {
    const response = await request.get(url, { failOnStatusCode: false, maxRedirects: 0, timeout: resolveTimeout(30_000) });
    lastTransportError = null;
    return response.status();
  } catch (error) {
    lastTransportError = error;
    return 0;
  }
}

async function pollStatus(request, url, expected, message, timeout) {
  lastTransportError = null;
  try {
    await expect
      .poll(() => statusOf(request, url), { message, timeout: resolveTimeout(timeout), intervals: [30_000] })
      .toBe(expected);
  } catch (failure) {
    if (!lastTransportError) throw failure;
    throw new Error(
      `${failure.message}\nlast transport error reaching ${url}: ${lastTransportError.message}`,
      { cause: failure },
    );
  }
}

exports.register = function (shared) {
  test("the deployed working tree is published in German with a language switcher", async ({ page, request }) => {
    test.setTimeout(resolveTimeout(5_400_000)); // the English and then the German Sphinx build of the deployed working tree
    expect(Object.keys(sample).length, "Expected German translations of README messages in docs.po").toBeGreaterThan(0);
    await pollStatus(
      request,
      `${shared.appBaseUrl}/deployed/de/`,
      200,
      "Expected the German site of the deployed working tree to be built",
      5_300_000,
    );

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
    await pollStatus(
      request,
      `${shared.appBaseUrl}/deployed/aa/`,
      404,
      "Expected the Afar path of the deployed working tree to answer 404",
      2_900_000,
    );
  });
};
