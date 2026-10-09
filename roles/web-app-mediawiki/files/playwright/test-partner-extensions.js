// Negative control for the partner-bridging addons of this role.
//
// Each of DiscourseSsoConsumer, MachineTranslation and PeerTubeEmbed derives
// its `enabled` from the matching services.<partner>.enabled flag, so a
// deployment without that partner must not carry the extension at all. The
// positive direction lives in files/playwright/addons/<id>.spec.js and runs in
// the integration-pair variant that co-deploys both roles; without this module
// the absent-partner branch is never asserted, and an extension that leaked
// into every deploy would look exactly like one that was correctly gated.

const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { isServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");

async function loadedExtensions(request) {
  const siteinfo = await request.get(
    `${appBaseUrl}/api.php?action=query&meta=siteinfo&siprop=extensions&format=json&formatversion=2`,
    { timeout: resolveTimeout(60_000) },
  );
  expect(
    siteinfo.status(),
    "the MediaWiki action API must answer so the loaded extension list can be read",
  ).toBe(200);
  return ((await siteinfo.json()).query?.extensions || []).map(
    (extension) => extension.name,
  );
}

test("discourse: no DiscourseSsoConsumer is loaded while the Discourse partner is absent", async ({
  request,
}) => {
  test.skip(isServiceEnabled("discourse"), "DISCOURSE_SERVICE_ENABLED=true");
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();

  expect(
    await loadedExtensions(request),
    "DiscourseSsoConsumer is loaded without a Discourse partner: its PluggableAuth provider then " +
      "points at an SSO endpoint nobody serves and the wiki login dead-ends",
  ).not.toContain("DiscourseSsoConsumer");
});

test("libretranslate: no MachineTranslation is loaded while the LibreTranslate partner is absent", async ({
  request,
}) => {
  test.skip(isServiceEnabled("libretranslate"), "LIBRETRANSLATE_SERVICE_ENABLED=true");
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();

  expect(
    await loadedExtensions(request),
    "MachineTranslation is loaded without a LibreTranslate partner: the wiki would offer a " +
      "translation surface whose backend does not exist",
  ).not.toContain("MachineTranslation");
});

test("peertube: no PeerTubeEmbed is loaded while the PeerTube partner is absent", async ({
  request,
}) => {
  test.skip(isServiceEnabled("peertube"), "PEERTUBE_SERVICE_ENABLED=true");
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();

  expect(
    await loadedExtensions(request),
    "PeerTubeEmbed is loaded without a PeerTube partner: its parser tag would render embeds for " +
      "an instance that is not deployed",
  ).not.toContain("PeerTubeEmbed");
});
