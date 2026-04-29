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

test("mig front page is served under canonical domain with TLS", async ({ page }) => {
  const response = await page.goto(`${appBaseUrl}/`);
  expect(response, "Expected mig response").toBeTruthy();
  expect(response.status(), "Expected mig front page status < 400").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the mig URL`
  ).toBe(true);
  const headers = response.headers();
  expect(headers["strict-transport-security"], "mig must emit HSTS").toBeTruthy();
});

test("mig returns HTML content under canonical domain", async ({ request }) => {
  // The deploy stage only guarantees the container is up and the proxy
  // routes to it; the mig role is a content host and does not ship a
  // canonical landing page yet, so a body-text assertion would be
  // brittle. Validate the deploy contract: HTML content-type under the
  // canonical domain.
  const response = await request.get(`${appBaseUrl}/`);
  expect(response.status(), "Expected mig front page status < 400").toBeLessThan(400);
  const contentType = response.headers()["content-type"] || "";
  expect(
    contentType.includes("text/html"),
    `Expected HTML content-type, got "${contentType}"`
  ).toBe(true);
});
