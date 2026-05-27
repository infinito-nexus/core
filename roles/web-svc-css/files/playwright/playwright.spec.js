const { test, expect } = require("@playwright/test");

const { assertInjectedAssetLoadsWithoutCspBlock, decodeDotenvQuotedValue } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const cssBaseUrl = decodeDotenvQuotedValue(process.env.CSS_BASE_URL || "");
const cdnBaseUrl = decodeDotenvQuotedValue(process.env.CDN_BASE_URL || "");

const cssAssetHosts = [cdnBaseUrl, cssBaseUrl]
  .filter(Boolean)
  .map((url) => {
    try {
      return new URL(url).host.toLowerCase();
    } catch {
      return null;
    }
  })
  .filter(Boolean);

const cssTargetRoles = (() => {
  const raw = process.env.CSS_TARGET_ROLES_JSON || "[]";
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
})();

test.beforeEach(() => {
  expect(
    cssAssetHosts.length,
    "CSS_BASE_URL and/or CDN_BASE_URL must be set in the Playwright env file"
  ).toBeGreaterThan(0);
});

test("css: shared CSS asset host is reachable", async ({ request }) => {
  const cdnBase = cdnBaseUrl.replace(/\/$/, "");
  const res = await request.get(`${cdnBase}/`, { ignoreHTTPSErrors: true });
  expect(
    res.status(),
    `GET ${cdnBase}/ must be reachable for downstream injection assertions (got ${res.status()})`
  ).toBeLessThan(500);
});

for (const target of cssTargetRoles) {
  test(`css: ${target.id} actually loads shared CSS asset without CSP block`, async ({ page }) => {
    const url = `${target.canonical_url.replace(/\/$/, "")}/`;
    await assertInjectedAssetLoadsWithoutCspBlock(page, {
      url,
      hostCandidates: cssAssetHosts,
      resourceTypes: ["stylesheet"],
      label: target.id,
    });
  });
}
