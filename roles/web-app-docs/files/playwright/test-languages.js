const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvJsonList, decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const preload = decodeDotenvJsonList(
  process.env.DOCS_I18N_PRELOAD_LANGUAGES_JSON,
  "DOCS_I18N_PRELOAD_LANGUAGES_JSON",
);
const samples = JSON.parse(decodeDotenvQuotedValue(process.env.DOCS_I18N_SAMPLES_JSON || "") || "{}");
const translated = preload.filter((code) => code in samples);

function normalized(text) {
  return (text || "").replace(/\s+/g, " ");
}

const { pollStatus } = require("./_shared");

exports.register = function (shared) {
  test.use({ trace: "off", video: "off" });

  test.describe(() => {
    test.describe.configure({ retries: 0 });

    for (const language of translated) {
      test(`the deployed working tree is published in ${language} with a language switcher`, async ({ page, request }) => {
        test.setTimeout(resolveTimeout(5_400_000));
        const sample = samples[language];
        expect(Object.keys(sample).length, `Expected ${language} translations of README messages in docs.po`).toBeGreaterThan(0);
        await pollStatus(
          request,
          `${shared.appBaseUrl}/deployed/${language}/`,
          200,
          `Expected the ${language} site of the deployed working tree to be built`,
          5_300_000,
        );

        await gotoOnion(page, `${shared.appBaseUrl}/deployed/${language}/`);
        expect(await page.locator("html").getAttribute("lang")).toBe(language);
        const text = normalized(await page.locator("body").textContent());
        expect(
          Object.values(sample).some((target) => text.includes(normalized(target))),
          `Expected a ${language} README message on /deployed/${language}/`,
        ).toBe(true);

        const switcher = page.locator("#docs-language-switcher");
        await expect(switcher.locator(`option[lang="${language}"]`)).toHaveCount(1, { timeout: resolveTimeout(30_000) });
        await expect(switcher.locator('option[lang="en"]')).toHaveCount(1);
        await Promise.all([
          page.waitForURL(`${shared.appBaseUrl}/deployed/index.html`, { timeout: resolveTimeout(30_000) }),
          switcher.selectOption({ label: "English" }),
        ]);
      });
    }
  });

  test("a language without a translated site answers 404", async ({ request }) => {
    test.setTimeout(resolveTimeout(3_000_000));
    await pollStatus(
      request,
      `${shared.appBaseUrl}/deployed/aa/`,
      404,
      "Expected the Afar path of the deployed working tree to answer 404",
      2_900_000,
    );
  });
};
