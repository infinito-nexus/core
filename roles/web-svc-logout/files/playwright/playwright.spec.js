const { test, expect } = require("@playwright/test");

const { assertInjectedAssetLoadsWithoutCspBlock, decodeDotenvQuotedValue, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = decodeDotenvQuotedValue(process.env.APP_BASE_URL);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);
const cdnBaseUrl = decodeDotenvQuotedValue(process.env.CDN_BASE_URL || "");

const cdnAssetHosts = [cdnBaseUrl]
  .filter(Boolean)
  .map((url) => {
    try {
      return new URL(url).host.toLowerCase();
    } catch {
      return null;
    }
  })
  .filter(Boolean);

test.beforeEach(() => {
  expect(appBaseUrl, "APP_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set in the Playwright env file").toBeTruthy();
  expect(
    cdnAssetHosts.length,
    "CDN_BASE_URL must be set in the Playwright env file (logout.js is served from the CDN host)"
  ).toBeGreaterThan(0);
});

const logoutTargetRoles = (() => {
  const raw = process.env.LOGOUT_TARGET_ROLES_JSON || "[]";
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
})();

for (const target of logoutTargetRoles) {
  test(`universal-logout: ${target.id} actually loads logout.js without CSP block`, async ({ page }) => {
    test.skip(
      Boolean(target.is_proxy_gated),
      `${target.id} is oauth2-proxy-gated: its anonymous landing is the IdP login page, so the injected logout.js is verified by that app's own authenticated persona e2e, not this anonymous check`
    );
    expect(
      target.canonical_url,
      `Expected canonical_url in LOGOUT_TARGET_ROLES_JSON entry for ${target.id}`
    ).toBeTruthy();
    const url = `${target.canonical_url.replace(/\/$/, "")}/`;

    const referenceResp = await page.request.get(url, { ignoreHTTPSErrors: true });
    expect(
      referenceResp.status(),
      `${target.id}: GET ${url} returned ${referenceResp.status()} — surface must respond for the logout assertion to be meaningful`
    ).toBeLessThan(500);
    const referenceHtml = await referenceResp.text();
    expect(
      referenceHtml,
      `${target.id}: HTML response from ${url} does not contain a 'logout.js' script reference`
    ).toContain("logout.js");

    await assertInjectedAssetLoadsWithoutCspBlock(page, {
      url,
      hostCandidates: cdnAssetHosts,
      resourceTypes: ["script"],
      label: target.id,
    });
  });
}

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas.js
// so every role's persona flow stays consistent.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page);
});
