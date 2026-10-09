const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");

const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const partnerBaseUrl = normalizeBaseUrl(
  decodeDotenvQuotedValue(process.env.PEERTUBE_BASE_URL || ""),
);

test("PeerTubeEmbed: the extension is loaded and registers its parser tag", async ({
  request,
}) => {
  skipUnlessAddonEnabled("PeerTubeEmbed");
  skipUnlessServiceEnabled("peertube");
  test.setTimeout(resolveTimeout(120_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(
    partnerBaseUrl,
    "PEERTUBE_BASE_URL must resolve to the deployed PeerTube partner once services.peertube.enabled is true",
  ).toBeTruthy();
  expect(
    new URL(partnerBaseUrl).host,
    "the embedded videos must come from the partner instance, not from the wiki itself",
  ).not.toBe(new URL(appBaseUrl).host);

  const siteinfo = await request.get(
    `${appBaseUrl}/api.php?action=query&meta=siteinfo&siprop=extensions|extensiontags&format=json&formatversion=2`,
    { timeout: resolveTimeout(60_000) },
  );
  expect(
    siteinfo.status(),
    "the MediaWiki action API must answer so the loaded extension list can be read",
  ).toBe(200);

  const payload = (await siteinfo.json()).query || {};
  expect(
    (payload.extensions || []).map((extension) => extension.name),
    "PeerTubeEmbed is not loaded; it is not bundled in the mediawiki image, so a missing tarball " +
      "or an unfinished composer install left it out of LocalSettings.php",
  ).toContain("PeerTubeEmbed");
  expect(
    (payload.extensiontags || []).some((tag) => /peertube/i.test(String(tag))),
    "the wiki advertises no PeerTube parser tag: the extension is loaded but its tag hook never " +
      "registered, so no wiki page can embed a partner video",
  ).toBe(true);
});
