const { test, expect } = require("@playwright/test");
const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("baseline: the Proxmox VE front page answers on the canonical domain", async ({ page }) => {
  const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
  const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
  await page.context().clearCookies();

  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected a Proxmox VE front response").toBeTruthy();
  expect(response.status(), "Expected the Proxmox VE front status < 500").toBeLessThan(500);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Proxmox VE URL`,
  ).toBe(true);
});
