const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue } = require("./personas");

const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

exports.register = function (shared) {
  test("moodle baseline: landing page reachable + canonical domain in URL", async ({ page }) => {
    const response = await page.goto(`${shared.env.moodleBaseUrl}/`);
    expect(response, "expected response").toBeTruthy();
    expect(response.status(), "landing status < 400").toBeLessThan(400);
    expect(
      response.url().includes(canonicalDomain),
      `expected canonical domain "${canonicalDomain}" in url`
    ).toBe(true);
  });

  test("moodle baseline: CSP header present, no violations on landing", async ({ page }) => {
    const response = await page.goto(`${shared.env.moodleBaseUrl}/`);
    const csp = response.headers()["content-security-policy"];
    expect(csp, "Content-Security-Policy header expected").toBeTruthy();
    await page.waitForTimeout(500);
    const violations = await page.evaluate(() => window.__cspViolations || []);
    expect(violations, `unexpected CSP violations: ${JSON.stringify(violations)}`).toEqual([]);
  });
};
