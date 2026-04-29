const { test, expect } = require("@playwright/test");

test.use({ ignoreHTTPSErrors: true });

function decodeDotenvQuotedValue(value) {
  if (typeof value !== "string" || value.length < 2) return value;
  if (!(value.startsWith('"') && value.endsWith('"'))) return value;
  const encoded = value.slice(1, -1);
  try {
    return JSON.parse(`"${encoded}"`).replace(/\$\$/g, "$");
  } catch {
    return encoded.replace(/\$\$/g, "$");
  }
}

function normalizeBaseUrl(value) {
  return decodeDotenvQuotedValue(value || "").replace(/\/$/, "");
}

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("sphinx front page is served under canonical domain with TLS", async ({ page }) => {
  const response = await page.goto(`${appBaseUrl}/`);
  expect(response, "Expected sphinx response").toBeTruthy();
  expect(response.status(), "Expected sphinx front page status < 400").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the sphinx URL`
  ).toBe(true);
  const headers = response.headers();
  expect(headers["strict-transport-security"], "sphinx must emit HSTS").toBeTruthy();
});

test("sphinx returns HTML content under canonical domain", async ({ request }) => {
  // Initial deploy serves an empty docs root (the docs are populated by a
  // separate Sphinx-build job, not by the deploy itself), so the front
  // page resolves to an Index-of listing rather than a Sphinx-rendered
  // page. Validate only what the deploy MUST guarantee at this stage:
  // an HTML response under the canonical domain. Theme/chrome assertions
  // belong in a follow-up suite once a docs-build step is part of the
  // role contract.
  const response = await request.get(`${appBaseUrl}/`);
  expect(response.status(), "Expected sphinx front page status < 400").toBeLessThan(400);
  const contentType = response.headers()["content-type"] || "";
  expect(
    contentType.includes("text/html"),
    `Expected HTML content-type, got "${contentType}"`
  ).toBe(true);
});
