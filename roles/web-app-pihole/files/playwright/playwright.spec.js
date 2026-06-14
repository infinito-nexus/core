// @ts-check
const { test, expect } = require("@playwright/test");

test.use({ ignoreHTTPSErrors: true });

function decodeDotenvQuotedValue(value) {
  if (typeof value !== "string" || value.length < 2) return value;
  if (!(value.startsWith('"') && value.endsWith('"'))) return value;
  const encoded = value.slice(1, -1);
  try { return JSON.parse(`"${encoded}"`).replace(/\$\$/g, "$"); }
  catch { return encoded.replace(/\$\$/g, "$"); }
}

const piholeBaseUrl = decodeDotenvQuotedValue(process.env.PIHOLE_BASE_URL);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.beforeEach(async ({ page }) => {
  expect(piholeBaseUrl, "PIHOLE_BASE_URL must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("Pi-hole front page is served under canonical domain with TLS", async ({ page }) => {
  const response = await page.goto(`${piholeBaseUrl.replace(/\/$/, "")}/`);
  expect(response, "Expected Pi-hole response").toBeTruthy();
  expect(response.status(), "Expected Pi-hole front page status < 400").toBeLessThan(400);
  if (canonicalDomain) {
    expect(
      response.url().includes(canonicalDomain),
      `Expected canonical domain "${canonicalDomain}" to back the Pi-hole URL`
    ).toBe(true);
  }
  const headers = response.headers();
  expect(headers["strict-transport-security"], "Pi-hole must emit HSTS").toBeTruthy();
});

test("Pi-hole returns HTML content under canonical domain", async ({ request }) => {
  const response = await request.get(`${piholeBaseUrl.replace(/\/$/, "")}/`);
  expect(response.status(), "Expected Pi-hole front page status < 400").toBeLessThan(400);
  const contentType = response.headers()["content-type"] || "";
  expect(
    contentType.includes("text/html"),
    `Expected HTML content-type, got "${contentType}"`
  ).toBe(true);
});

// Persona/SSO-specific scenarios live in their own files:
// test-guest.js (unauthenticated redirect to Keycloak when SSO enabled)
// test-oauth2.js (administrator/biber SSO login, access control, logout)
// test-native.js (native admin login when SSO disabled)
