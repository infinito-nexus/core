const { test, expect } = require("@playwright/test");

const {
  assertInjectedAssetLoadsWithoutCspBlock,
  decodeDotenvJsonList,
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

for (const target of designTargetRoles) {
  test(`design: ${target.id} actually loads shared CSS asset without CSP block`, async ({ page }) => {
    const url = `${target.canonical_url.replace(/\/$/, "")}/`;
    await assertInjectedAssetLoadsWithoutCspBlock(page, {
      url,
      hostCandidates: designAssetHosts,
      resourceTypes: ["stylesheet"],
      label: target.id,
    });
  });
}
