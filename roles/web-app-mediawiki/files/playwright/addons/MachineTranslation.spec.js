const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");

const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const partnerBaseUrl = normalizeBaseUrl(
  decodeDotenvQuotedValue(process.env.LIBRETRANSLATE_BASE_URL || ""),
);

test("MachineTranslation: the extension is loaded and the LibreTranslate partner answers as a distinct host", async ({
  request,
}) => {
  skipUnlessAddonEnabled("MachineTranslation");
  skipUnlessServiceEnabled("libretranslate");
  test.setTimeout(resolveTimeout(120_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(
    partnerBaseUrl,
    "LIBRETRANSLATE_BASE_URL must resolve to the deployed LibreTranslate partner once services.libretranslate.enabled is true",
  ).toBeTruthy();
  expect(
    new URL(partnerBaseUrl).host,
    "the translation backend must be the partner instance, not the wiki itself",
  ).not.toBe(new URL(appBaseUrl).host);

  const siteinfo = await request.get(
    `${appBaseUrl}/api.php?action=query&meta=siteinfo&siprop=extensions&format=json&formatversion=2`,
    { timeout: resolveTimeout(60_000) },
  );
  expect(
    siteinfo.status(),
    "the MediaWiki action API must answer so the loaded extension list can be read",
  ).toBe(200);

  const installed = ((await siteinfo.json()).query?.extensions || []).map(
    (extension) => extension.name,
  );
  expect(
    installed,
    "MachineTranslation is not loaded; it is not bundled in the mediawiki image, so a missing " +
      "tarball or an unfinished composer install left it out of LocalSettings.php",
  ).toContain("MachineTranslation");

  const languages = await request.get(`${partnerBaseUrl}/languages`, {
    timeout: resolveTimeout(60_000),
  });
  expect(
    languages.status(),
    "the LibreTranslate partner must serve its /languages catalogue; without it the extension has " +
      "no translation backend and every translation request fails at runtime",
  ).toBe(200);
  expect(
    (await languages.json()).length,
    "the LibreTranslate partner must advertise at least one language model",
  ).toBeGreaterThan(0);
});
