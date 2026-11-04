const { test, expect } = require("@playwright/test");

const {
  appBaseUrl,
  oidcIssuerUrl,
  matomoApiToken,
  matomoTrackingScope,
  matomoCanonicalDomain,
  matomoTargetRoles,
  hostOf,
  siteNeedleFor,
  setupMatomoPage,
  loginAsAdmin,
} = require("./_shared");
const { assertInjectedAssetLoadsWithoutCspBlock, gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const SET_SITE_ID_CALL = /_paq\s*\.\s*push\s*\(\s*\[\s*['"]setSiteId['"]/g;

function countTrackers(html) {
  return (String(html).match(SET_SITE_ID_CALL) || []).length;
}

/**
 * Args:
 *   page: the Playwright page.
 *   target: the MATOMO_TARGET_ROLES_JSON entry under test.
 *   url: the target's canonical URL.
 * Skips the running test when the anonymous visitor of url lands on the IdP.
 */
async function skipWhenLandingOnIdp(page, target, url) {
  const referenceResp = await page.request.get(url, { ignoreHTTPSErrors: true });
  expect(
    referenceResp.status(),
    `${target.id}: GET ${url} returned ${referenceResp.status()} — surface must respond for the tracker assertion to be meaningful`
  ).toBeLessThan(500);
  const referenceHtml = await referenceResp.text();
  const injected = referenceHtml.includes(matomoCanonicalDomain);
  const ownHost = new URL(url).host;
  let landedHost = new URL(referenceResp.url()).host;
  if (landedHost === ownHost && !injected) {
    await gotoOnion(page, url, { waitUntil: "domcontentloaded" });
    await page
      .waitForURL((landed) => new URL(landed).host !== ownHost, { timeout: resolveTimeout(15_000) })
      .catch(() => {});
    landedHost = new URL(page.url()).host;
  }
  if (landedHost !== ownHost && !injected) {
    const idpHost = new URL(oidcIssuerUrl).host;
    expect(
      landedHost,
      `${target.id}: anonymous GET ${url} landed on ${landedHost}, which is neither its own host nor the IdP ${idpHost} — that is a routing fault, not an SSO handoff`
    ).toBe(idpHost);
    test.skip(true, `${target.id}: its anonymous surface auto-redirects to the IdP (app-level SSO), so the tracker this check would observe is the IdP's, not ${target.id}'s`);
  }
}

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async ({ page }) => {
  await setupMatomoPage(page);
});

test("matomo SitesManager registers a tracker site for every consumer role", async ({ page, request }) => {
  test.skip(matomoTargetRoles.length === 0, "no matomo consumer roles in inventory");

  await loginAsAdmin(page);

  const cookies = await page.context().cookies();
  await request.storageState();

  // token_auth: session cookie alone yields 401; POST keeps the token out of the URL
  const apiBase = `${appBaseUrl}/index.php`;
  const apiResp = await page.request.post(apiBase, {
    form: {
      module: "API",
      method: "SitesManager.getAllSites",
      format: "JSON",
      token_auth: matomoApiToken,
    },
    ignoreHTTPSErrors: true,
  });
  expect(
    apiResp.status(),
    `Matomo SitesManager.getAllSites MUST respond < 400 (got ${apiResp.status()})`
  ).toBeLessThan(400);

  const sites = await apiResp.json().catch(() => []);
  expect(Array.isArray(sites), "Matomo SitesManager.getAllSites MUST return an array").toBe(true);

  const failures = [];
  for (const target of matomoTargetRoles) {
    const needle = siteNeedleFor(target.canonical_domain);
    if (!needle) {
      failures.push(`${target.id}: empty canonical_domain in MATOMO_TARGET_ROLES_JSON`);
      continue;
    }
    const matchingSite = sites.find((site) => {
      const candidates = [
        String(site?.main_url || ""),
        ...(Array.isArray(site?.alias_urls) ? site.alias_urls.map(String) : []),
      ];
      return candidates.some((c) => hostOf(c) === needle);
    });
    if (!matchingSite) {
      failures.push(`${target.id}: no Matomo site main_url / alias_urls host equals tracking site domain "${needle}" (scope "${matomoTrackingScope}", canonical "${target.canonical_domain}")`);
    }
  }

  expect(
    failures,
    `Matomo SitesManager coverage failures:\n  - ${failures.join("\n  - ")}`
  ).toEqual([]);

  // `cookies` is referenced once so the variable is not flagged as unused; the
  // cookies already sit on `page.request`, the array is kept for post-mortem.
  void cookies;
});

for (const target of matomoTargetRoles) {
  test(`matomo tracker injected in ${target.id} (${target.canonical_domain})`, async ({ page }) => {
    test.skip(
      Boolean(target.is_proxy_gated),
      `${target.id} is oauth2-proxy-gated: its anonymous landing is the IdP login page, so the injected tracker is verified by that app's own authenticated persona e2e, not this anonymous check`
    );
    expect(
      target.canonical_url,
      `Expected canonical_url in MATOMO_TARGET_ROLES_JSON entry for ${target.id}`
    ).toBeTruthy();
    const targetUrl = `${target.canonical_url.replace(/\/$/, "")}/`;
    await skipWhenLandingOnIdp(page, target, targetUrl);

    if (matomoCanonicalDomain) {
      await assertInjectedAssetLoadsWithoutCspBlock(page, {
        url: targetUrl,
        hostCandidates: [matomoCanonicalDomain],
        resourceTypes: ["script"],
        label: target.id,
      });
    } else {
      await gotoOnion(page, targetUrl, { waitUntil: "domcontentloaded" });
    }

    const html = await page.content();
    expect(
      html,
      `Expected matomo tracker '_paq' marker in ${target.id} HTML body`
    ).toContain("_paq");

    expect(
      html,
      `Expected matomo tracker URL ('matomo.php') in ${target.id} HTML body`
    ).toContain("matomo.php");

    if (matomoCanonicalDomain) {
      expect(
        html,
        `Expected matomo host '${matomoCanonicalDomain}' referenced in ${target.id} HTML body`
      ).toContain(matomoCanonicalDomain);
    }

    expect(
      countTrackers(html),
      `Exactly one Matomo tracker must reach ${target.id}. Two means the snippet was injected twice and every visit is double-counted.`
    ).toBe(1);
  });
}
