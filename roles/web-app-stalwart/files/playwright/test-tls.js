const { test, expect } = require("@playwright/test");

const { appBaseUrl, canonicalDomain } = require("./env");
const { gotoOnion } = require("./personas");
const { resolveTimeout, isOnionTarget } = require("./timeouts");

// Baseline reachability: WebAdmin TLS + DAV auto-discovery through the proxy.
test("stalwart: WebAdmin is served under canonical domain with TLS", async ({ page }) => {
  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected Stalwart response").toBeTruthy();
  expect(response.status(), "Expected status < 400").toBeLessThan(400);
  expect(response.url().includes(canonicalDomain), `Expected canonical domain "${canonicalDomain}"`).toBe(true);
  if (!isOnionTarget()) {
    expect(response.headers()["strict-transport-security"], "Stalwart must emit HSTS").toBeTruthy();
  }
});

test("stalwart: CalDAV/CardDAV discovery is reachable", async ({ request }) => {
  for (const [wk, path] of [["caldav", "/dav/cal"], ["carddav", "/dav/card"]]) {
    const res = await request.get(`${appBaseUrl}/.well-known/${wk}`, {
      maxRedirects: 0,
      timeout: resolveTimeout(30_000),
    });
    expect([301, 302, 307, 308].includes(res.status()),
      `${wk} well-known must redirect (got ${res.status()})`).toBe(true);
    expect(res.headers()["location"] || "", `${wk} should point at ${path}`).toContain("/dav/");
  }
});
