const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");

const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const partnerBaseUrl = normalizeBaseUrl(
  decodeDotenvQuotedValue(process.env.DISCOURSE_BASE_URL || ""),
);

test("DiscourseSsoConsumer: the extension is loaded on top of PluggableAuth and the Discourse partner is a distinct host", async ({
  request,
}) => {
  skipUnlessAddonEnabled("DiscourseSsoConsumer");
  skipUnlessServiceEnabled("discourse");
  test.setTimeout(resolveTimeout(120_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(
    partnerBaseUrl,
    "DISCOURSE_BASE_URL must resolve to the deployed Discourse partner once services.discourse.enabled is true",
  ).toBeTruthy();
  expect(
    new URL(partnerBaseUrl).host,
    "the Discourse SSO provider must be the partner instance, not the wiki itself",
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
    "DiscourseSsoConsumer is not loaded; it is not bundled in the mediawiki image, so a missing " +
      "tarball or an unfinished composer install left it out of LocalSettings.php",
  ).toContain("DiscourseSsoConsumer");
  expect(
    installed,
    "PluggableAuth is missing: DiscourseSsoConsumer is a PluggableAuth provider and authenticates " +
      "nobody without it, so the wiki would keep its own login form while the addon looks installed",
  ).toContain("PluggableAuth");
});
