// nocheck: playwright-env-template  The agent fixture is a deliberately weak detection target verified by the hacker and counsel agent scenarios, not by the standard persona Playwright runner, so it ships no playwright.env.j2 and is deliberately left out of the per-app e2e discovery.
const { test, expect } = require("@playwright/test");

const appBaseUrl = (process.env.APP_BASE_URL || "").replace(/\/+$/, "");

test("Agent fixture front page is served", async ({ request }) => {
  const response = await request.get(`${appBaseUrl}/`);
  expect(response.status(), "Expected the fixture front page status < 400").toBeLessThan(400);
  const contentType = response.headers()["content-type"] || "";
  expect(contentType.includes("text/html"), `Expected HTML, got "${contentType}"`).toBe(true);
});
