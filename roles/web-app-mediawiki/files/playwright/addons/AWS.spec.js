const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");

const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");

test("AWS: the extension is loaded and the wiki accepts uploads", async ({ request }) => {
  skipUnlessAddonEnabled("AWS");
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(resolveTimeout(120_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();

  const siteinfo = await request.get(
    `${appBaseUrl}/api.php?action=query&meta=siteinfo&siprop=general|extensions&format=json&formatversion=2`,
    { timeout: resolveTimeout(60_000) },
  );
  expect(
    siteinfo.status(),
    "the MediaWiki action API must answer so the loaded extension list can be read",
  ).toBe(200);

  const payload = (await siteinfo.json()).query || {};
  const installed = (payload.extensions || []).map((extension) => extension.name);
  expect(
    installed,
    "AWS is not loaded; it is not bundled in the mediawiki image, so a missing tarball or an " +
      "unfinished composer install left LocalSettings.php's vendor/autoload.php guard closed",
  ).toContain("AWS");

  expect(
    payload.general?.uploadsenabled,
    "$wgEnableUploads must be true: Extension:AWS only replaces $wgLocalFileRepo, it does not " +
      "open an upload surface of its own, so a false flag leaves the bucket unreachable",
  ).toBe(true);
});
