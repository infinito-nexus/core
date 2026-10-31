const { test, expect } = require("@playwright/test");

const {
  assertInjectedAssetLoadsWithoutCspBlock,
  decodeDotenvJsonList,
  gotoOnion,
  requireDotenvValue,
} = require("./personas");
const { resolveTimeout } = require("./timeouts");

test.use({ ignoreHTTPSErrors: true });

const designBaseUrl = requireDotenvValue(
  process.env.DESIGN_BASE_URL,
  "DESIGN_BASE_URL"
);
const cdnBaseUrl = requireDotenvValue(process.env.CDN_BASE_URL, "CDN_BASE_URL");

const designAssetHosts = [cdnBaseUrl, designBaseUrl]
  .filter(Boolean)
  .map((url) => {
    try {
      return new URL(url).host.toLowerCase();
    } catch {
      return null;
    }
  })
  .filter(Boolean);

const designTargetRoles = decodeDotenvJsonList(
  process.env.DESIGN_TARGET_ROLES_JSON,
  "DESIGN_TARGET_ROLES_JSON"
);

test.beforeEach(() => {
  expect(
    designAssetHosts.length,
    "DESIGN_BASE_URL and/or CDN_BASE_URL must be set in the Playwright env file"
  ).toBeGreaterThan(0);
});

test("design: shared CSS asset host is reachable", async ({ request }) => {
  const cdnBase = cdnBaseUrl.replace(/\/$/, "");
  const res = await request.get(`${cdnBase}/`, {
    ignoreHTTPSErrors: true,
    timeout: resolveTimeout(30_000),
  });
  expect(
    res.status(),
    `GET ${cdnBase}/ must be reachable for downstream injection assertions (got ${res.status()})`
  ).toBeLessThan(500);
});

/**
 * Args:
 *   page: the Playwright page.
 *   target: the DESIGN_TARGET_ROLES_JSON entry under test.
 *   url: the target's canonical URL.
 * Skips the running test when the anonymous visitor of url lands on the IdP.
 */
async function skipWhenLandingOnIdp(page, target, url) {
  const referenceResp = await page.request.get(url, { ignoreHTTPSErrors: true });
  expect(
    referenceResp.status(),
    `${target.id}: GET ${url} returned ${referenceResp.status()} — surface must respond for the design assertion to be meaningful`
  ).toBeLessThan(500);
  const referenceHtml = await referenceResp.text();
  const injected = designAssetHosts.some((host) => referenceHtml.includes(host));
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
    const idpHost = new URL(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL")).host;
    expect(
      landedHost,
      `${target.id}: anonymous GET ${url} landed on ${landedHost}, which is neither its own host nor the IdP ${idpHost} — that is a routing fault, not an SSO handoff`
    ).toBe(idpHost);
    test.skip(true, `${target.id}: its anonymous surface auto-redirects to the IdP (app-level SSO), so the stylesheet this check would observe is the IdP's, not ${target.id}'s`);
  }
}

for (const target of designTargetRoles) {
  test(`design: ${target.id} actually loads shared CSS asset without CSP block`, async ({ page }) => {
    test.skip(
      Boolean(target.is_proxy_gated),
      `${target.id} is oauth2-proxy-gated: its anonymous landing is the IdP login page, so the injected CSS is verified by that app's own authenticated persona e2e, not this anonymous check`
    );
    const url = `${target.canonical_url.replace(/\/$/, "")}/`;
    await skipWhenLandingOnIdp(page, target, url);
    await assertInjectedAssetLoadsWithoutCspBlock(page, {
      url,
      hostCandidates: designAssetHosts,
      resourceTypes: ["stylesheet"],
      label: target.id,
    });
  });
}
