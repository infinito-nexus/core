const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

// Functional cross-role coupling check for nextcloud/integration_peertube.
//
// The upstream integration_peertube app is a unified-search + link-preview
// connector keyed solely on the admin `instances` app value; it exposes no
// per-user OAuth "Connect to PeerTube" control (no client_id/client_secret/
// oauth_instance_url config, no /oauth/authorize flow). The only thing the addon
// hook provisions is that admin value:
//   instances = lookup('tls','web-app-peertube','url.base')   (the partner host).
//
// The real coupling this app provides is therefore twofold:
//   1. the admin panel `instances` field is pinned to the EXACT deployed PeerTube
//      partner host (PEERTUBE_BASE_URL, = the same url.base the addon provisions),
//      not a stale/placeholder/wrong-partner URL, and
//   2. the value actually unlocks behaviour: the app registers a PeerTube
//      provider in Nextcloud's unified-search registry — the functional surface
//      the `instances` value exists to power.
// When the addon is enabled both MUST hold; a missing panel, an instances host
// that is not the partner, or a missing search provider means the coupling failed
// to provision and the test FAILS (it does not skip).
test("integration integration_peertube: admin panel pins the partner host and registers the PeerTube search provider", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_peertube");
  test.setTimeout(resolveTimeout(120_000));

  const partnerBaseUrl = (shared.env.peertubeBaseUrl || "").trim();
  expect(
    /^https?:\/\//i.test(partnerBaseUrl),
    "PEERTUBE_BASE_URL must resolve to the deployed partner PeerTube base URL when integration_peertube is enabled (it is the same url.base the addon hook writes into the `instances` app value)"
  ).toBeTruthy();

  const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
  const partnerHost = new URL(partnerBaseUrl).host;
  expect(
    partnerHost,
    "the deployed PeerTube partner host must be distinct from the Nextcloud host"
  ).not.toBe(nextcloudHost);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    // Coupling signal 1: the admin PeerTube panel must render and its allowed-
    // instances field must be pinned to the EXACT partner host. A non-empty value
    // that merely differs from Nextcloud is not enough — a stale/placeholder/
    // wrong-partner URL would green-wash; assert host EQUALS the partner.
    await gotoOnion(page,
      new URL("settings/admin/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const peertubePanel = page
      .locator("#peertube_prefs, #peertube, #peertube-content")
      .first();
    await expect(
      peertubePanel,
      "the PeerTube integration admin panel must render when integration_peertube is enabled — its absence means the app failed to install/configure and the coupling never landed"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const instancesField = peertubePanel
      .locator("#peertube-instances")
      .or(peertubePanel.locator("textarea"))
      .first();
    await expect(
      instancesField,
      "the PeerTube admin panel must expose the allowed-instances field"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    const configuredInstances = ((await instancesField.inputValue().catch(() => "")) || "").trim();
    const firstInstance = configuredInstances
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .find((s) => /^https?:\/\//i.test(s));
    expect(
      firstInstance,
      "the PeerTube admin instances field must be populated with an absolute partner URL (addon hook sets the `instances` app value)"
    ).toBeTruthy();

    const instanceHost = new URL(firstInstance).host;
    expect(
      instanceHost,
      "the configured PeerTube instance must be the partner instance, not Nextcloud itself"
    ).not.toBe(nextcloudHost);
    expect(
      instanceHost,
      "the PeerTube admin `instances` value must point at the EXACT deployed PeerTube partner host (lookup('tls','web-app-peertube','url.base')); a stale/placeholder/wrong-partner URL would otherwise pass"
    ).toBe(partnerHost);

    // Coupling signal 2 (functional smoke): the value above only matters because
    // integration_peertube registers a unified-search provider that queries the
    // configured instances. Assert that provider is actually registered via the
    // authenticated OCS search-providers registry — the same OCS-APIRequest
    // mechanism the sibling specs use. This fails for an enabled-but-non-functional
    // install where the app is present but its search provider never registered.
    const searchProvidersUrl = new URL(
      "ocs/v2.php/search/providers?format=json",
      shared.env.nextcloudBaseUrl
    ).toString();
    const searchProvidersResponse = await page.request.get(searchProvidersUrl, {
      headers: { "OCS-APIRequest": "true", Accept: "application/json" },
    });
    expect(
      searchProvidersResponse.ok(),
      "the OCS unified-search providers endpoint must respond to the authenticated session"
    ).toBeTruthy();

    const searchProvidersBody = await searchProvidersResponse.json();
    const providers = searchProvidersBody?.ocs?.data;
    expect(
      Array.isArray(providers),
      "the OCS search-providers response must carry an ocs.data array of registered providers"
    ).toBeTruthy();

    const peertubeProvider = providers.find(
      (p) => /peertube/i.test(String(p?.id ?? "")) || /peertube/i.test(String(p?.name ?? ""))
    );
    expect(
      peertubeProvider,
      "integration_peertube must register a PeerTube provider in the unified-search registry — its absence proves the app is enabled-but-non-functional (the `instances` value never unlocked the search surface it exists to power), which must FAIL rather than silently pass"
    ).toBeTruthy();
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
